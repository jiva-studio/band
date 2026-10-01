import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROTECTED_PATH_PATTERNS = [
    "*/artifacts/state.json",
    "artifacts/state.json",
    "*/.agents/tasks/*/artifacts/state.json",
    "*/.agents/tasks/*/state.json",
    ".agents/tasks/*/state.json",
    ".agents/tasks/*/artifacts/state.json",
    "*/.agents/pipelines/*",
    ".agents/pipelines/*",
    "*/.agents/band/*",
    ".agents/band/*",
    "*/.agents/bin/*",
    ".agents/bin/*",
    "*pipelines/*.yaml",
    "*pipelines/*.yml",
]

_REL_SETTINGS = r"""(?:^|[\s'"=>])(?:\./)?\.(?:agents|claude)/settings\.json"""
PROJECT_SETTINGS_RE = r"(?:(?:>|>>)\s*|(?:sed|perl)\s+.*-i.*|(?:rm|mv|ln|truncate)\s+.*)" + _REL_SETTINGS

DANGEROUS_COMMAND_PATTERNS = [
    r"(>|>>)\s*.*state\.json",
    r"sed\s+.*-i.*state\.json",
    r"rm\s+.*state\.json",
    r"mv\s+.*state\.json",
    r"cp\s+.*state\.json",
    r"python[0-9.]*\s+.*state\.json",
    r"(>|>>)\s*.*\.agents/pipelines",
    r"(>|>>)\s*.*\.agents/band",
    r"(>|>>)\s*.*\.agents/bin",
    # Project Claude Code settings (Band's hooks). Relative forms only, so the
    # user's global ~/.claude/settings.json is not affected.
    PROJECT_SETTINGS_RE,
]

# Keys under which harnesses pass the target file path of an edit tool.
# Claude Code: Edit/Write/MultiEdit -> file_path, NotebookEdit -> notebook_path.
PATH_ARG_KEYS = ["file_path", "notebook_path", "target_file", "TargetFile", "path", "file", "filename", "target"]

# Tools that modify the file named by their path argument. Read-only tools (Read,
# Grep, Glob) also carry path args and must not be checked against stage boundaries.
EDIT_TOOL_NAMES = {"edit", "write", "multiedit", "notebookedit"}
EDIT_TOOL_KEYWORDS = ("edit", "write", "replace", "create", "patch", "insert", "delete", "rename", "move")


def is_edit_tool(tool_name: Any) -> bool:
    if not isinstance(tool_name, str) or not tool_name:
        return False
    name = tool_name.lower()
    return name in EDIT_TOOL_NAMES or any(kw in name for kw in EDIT_TOOL_KEYWORDS)


def repo_relative_path(path_str: str, repo_root: Optional[str] = None, cwd: Optional[str] = None) -> Optional[str]:
    """Maps an edit target to a repo-relative POSIX path; None if it lies outside the repository."""
    if not path_str:
        return None
    if repo_root is None:
        from band.config import REPO_ROOT
        repo_root = str(REPO_ROOT)
    root = Path(repo_root).resolve()
    p = Path(path_str.replace("\\", "/")).expanduser()
    if not p.is_absolute():
        p = Path(cwd or os.getcwd()) / p
    try:
        return p.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


# Keys under which harnesses pass a shell command. Claude Code: Bash -> command.
COMMAND_ARG_KEYS = ["command", "CommandLine", "cmd", "script"]


def is_path_protected(path_str: str) -> bool:
    """Checks if a file path targets a protected internal state or engine file."""
    if not path_str:
        return False

    normalized = path_str.replace("\\", "/").strip()
    p = Path(normalized)

    # Check exact filename for state.json inside any artifacts/ folder
    if p.name == "state.json" and ("artifacts" in normalized or ".agents" in normalized or "tasks" in normalized):
        return True

    for pattern in PROTECTED_PATH_PATTERNS:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(f"*/{normalized}", pattern):
            return True
        if pattern.replace("*", "") in normalized:
            return True

    return False


def is_project_settings(path_str: str, project_root: Optional[str] = None) -> bool:
    """
    True if path_str is the project's Claude Code settings file carrying Band's hooks:
    <project>/.agents/settings.json, also reached as <project>/.claude/settings.json
    through the .claude -> .agents symlink. The user's ~/.claude/settings.json and
    settings.local.json are not protected.
    """
    if not path_str:
        return False
    root = Path(project_root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    p = Path(path_str.replace("\\", "/")).expanduser()
    if not p.is_absolute():
        p = root / p
    try:
        resolved = p.resolve()
        root_resolved = root.resolve()
    except OSError:
        return False
    targets = {(root_resolved / ".agents" / "settings.json"), (root_resolved / ".claude" / "settings.json")}
    return resolved in targets


def is_command_dangerous(command_str: str) -> Tuple[bool, str]:
    """Inspects a shell command line for attempts to tamper with protected state."""
    if not command_str:
        return False, ""

    cmd = command_str.strip()

    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True, f"Command matches dangerous write pattern: {pattern}"

    if "state.json" in cmd and any(kw in cmd for kw in ["open(", "write(", "dump(", "truncate", ">", "echo"]):
        return True, "Command appears to modify state.json directly."

    return False, ""


def evaluate_tool_call(
    payload: Dict[str, Any],
    stage: Optional[Dict[str, Any]] = None,
    repo_root: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Evaluates an incoming PreToolUse hook payload.

    Accepts both Claude Code payloads ({"hook_event_name": "PreToolUse",
    "tool_name": "Edit", "tool_input": {"file_path": ...}}) and the legacy
    dialect ({"name"/"tool": ..., "args"/"arguments"/"params": {...}}).
    When ``stage`` (the active pipeline stage) is given, edit tools are also
    checked against its ``allow``/``deny`` file boundary.
    Returns (is_allowed, reason_if_denied).
    """
    if not isinstance(payload, dict):
        return True, ""

    args = payload.get("tool_input") or payload.get("args") or payload.get("arguments") or payload.get("params") or {}

    if not isinstance(args, dict):
        return True, ""

    # Check file editing tools
    for key in PATH_ARG_KEYS:
        target_path = args.get(key)
        if isinstance(target_path, str) and (
            is_path_protected(target_path) or is_project_settings(target_path, payload.get("cwd"))
        ):
            return False, f"Direct editing of protected path '{target_path}' is forbidden. State transitions are managed exclusively by the Band harness."

    # Check the active stage's allow/deny file boundary
    tool_name = payload.get("tool_name") or payload.get("name") or payload.get("tool")
    if stage and is_edit_tool(tool_name):
        from band.pipeline_runner import stage_path_violation
        for key in PATH_ARG_KEYS:
            target_path = args.get(key)
            if not isinstance(target_path, str):
                continue
            rel = repo_relative_path(target_path, repo_root, payload.get("cwd"))
            if rel is None:
                continue
            violation = stage_path_violation(stage, rel)
            if violation:
                stage_id = stage.get("id", "stage")
                return False, (
                    f"Stage [{stage_id}] ({stage.get('role', stage_id)}) may not edit '{rel}': {violation}. "
                    "Stay within this stage's file boundary."
                )

    # Check command execution tools
    for key in COMMAND_ARG_KEYS:
        command_text = args.get(key)
        if isinstance(command_text, str):
            is_dang, reason = is_command_dangerous(command_text)
            if is_dang:
                return False, f"Command forbidden by Band security guard: {reason}"

    return True, ""


def run_guard(harness: str = "auto", stage_resolver: Optional[Callable[[], Optional[Dict[str, Any]]]] = None):
    """Entry point for PreToolUse hook runner (Claude Code or legacy dialect)."""
    from band.hook_io import read_stdin_payload, detect_harness, guard_response, emit

    payload = read_stdin_payload()
    resolved = detect_harness(payload, harness)
    stage = None
    if stage_resolver is not None:
        try:
            stage = stage_resolver()
        except Exception:
            stage = None  # The Stop-hook boundary check still applies.
    is_allowed, reason = evaluate_tool_call(payload, stage)
    emit(guard_response(is_allowed, reason, resolved))


if __name__ == "__main__":
    run_guard()

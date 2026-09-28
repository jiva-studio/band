import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
]

# Keys under which harnesses pass the target file path of an edit tool.
# Claude Code: Edit/Write/MultiEdit -> file_path, NotebookEdit -> notebook_path.
PATH_ARG_KEYS = ["file_path", "notebook_path", "target_file", "TargetFile", "path", "file", "filename", "target"]

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


def evaluate_tool_call(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Evaluates an incoming PreToolUse hook payload.

    Accepts both Claude Code payloads ({"hook_event_name": "PreToolUse",
    "tool_name": "Edit", "tool_input": {"file_path": ...}}) and the legacy
    dialect ({"name"/"tool": ..., "args"/"arguments"/"params": {...}}).
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
        if isinstance(target_path, str) and is_path_protected(target_path):
            return False, f"Direct editing of protected path '{target_path}' is forbidden. State transitions are managed exclusively by the Band harness."

    # Check command execution tools
    for key in COMMAND_ARG_KEYS:
        command_text = args.get(key)
        if isinstance(command_text, str):
            is_dang, reason = is_command_dangerous(command_text)
            if is_dang:
                return False, f"Command forbidden by Band security guard: {reason}"

    return True, ""


def run_guard(harness: str = "auto"):
    """Entry point for PreToolUse hook runner (Claude Code or legacy dialect)."""
    from band.hook_io import read_stdin_payload, detect_harness, guard_response, emit

    payload = read_stdin_payload()
    resolved = detect_harness(payload, harness)
    is_allowed, reason = evaluate_tool_call(payload)
    emit(guard_response(is_allowed, reason, resolved))


if __name__ == "__main__":
    run_guard()

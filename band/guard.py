import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROTECTED_PATH_PATTERNS = [
    "*/artifacts/state.json",
    "artifacts/state.json",
    "*.agents/tasks/*/artifacts/state.json",
    "*.agents/pipelines/*",
    "*.agents/band/*",
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
]


def is_path_protected(path_str: str) -> bool:
    """Checks if a file path targets a protected internal state or engine file."""
    if not path_str:
        return False

    normalized = path_str.replace("\\", "/").strip()
    p = Path(normalized)

    # Check exact filename for state.json inside any artifacts/ folder
    if p.name == "state.json":
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
    Returns (is_allowed, reason_if_denied).
    """
    tool_name = (
        payload.get("tool_name")
        or payload.get("name")
        or payload.get("tool")
        or payload.get("matcher", "")
    )
    args = payload.get("tool_input") or payload.get("args") or payload.get("arguments") or payload.get("params") or {}

    if not isinstance(args, dict):
        return True, ""

    # Check file editing tools
    for key in ["target_file", "TargetFile", "path", "file_path", "file", "filename", "target"]:
        target_path = args.get(key)
        if isinstance(target_path, str) and is_path_protected(target_path):
            return False, f"Direct editing of protected path '{target_path}' is forbidden. State transitions are managed exclusively by the Band harness."

    # Check command execution tools
    for key in ["command", "CommandLine", "cmd", "script"]:
        command_text = args.get(key)
        if isinstance(command_text, str):
            is_dang, reason = is_command_dangerous(command_text)
            if is_dang:
                return False, f"Command forbidden by Band security guard: {reason}"

    return True, ""


def run_guard():
    """Entry point for PreToolUse hook runner."""
    raw_input = ""
    try:
        if not sys.stdin.isatty():
            raw_input = sys.stdin.read().strip()
    except Exception:
        raw_input = ""

    payload = {}
    if raw_input:
        try:
            payload = json.loads(raw_input)
        except Exception:
            payload = {"raw": raw_input}

    is_allowed, reason = evaluate_tool_call(payload)

    if not is_allowed:
        sys.stderr.write(f"\n🚫 [BAND PRE-TOOL GATE] {reason}\n")
        response = {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
            "decision": "deny",
            "reason": reason,
        }
        print(json.dumps(response, indent=2))
        sys.exit(2)
    else:
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)


if __name__ == "__main__":
    run_guard()

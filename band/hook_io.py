"""Hook I/O adapters: read hook payloads and emit decisions per harness.

Two harness dialects are supported:

* ``claude-code`` - Claude Code hooks (``.claude/settings.json``). The event
  arrives as JSON on stdin (``hook_event_name``, ``tool_name``,
  ``tool_input``...). Blocking is signalled with exit code 2 plus the reason
  on stderr, which every Claude Code version honours for PreToolUse and Stop;
  the documented JSON form is printed on stdout as well. Allowing is a
  silent exit 0 (we never emit ``permissionDecision: allow`` because that
  would bypass the user's own permission prompts).
* ``legacy`` - the original ``.agents/hooks.json`` dialect used by other
  harnesses: ``{"decision": "allow"|"deny"|"continue", "reason": ...}``.
"""

import json
import sys
from typing import Any, Dict, Optional, TextIO

HARNESS_CLAUDE = "claude-code"
HARNESS_LEGACY = "legacy"
HARNESS_AUTO = "auto"
HARNESS_CHOICES = (HARNESS_AUTO, HARNESS_CLAUDE, HARNESS_LEGACY)


def read_stdin_payload(stream: Optional[TextIO] = None) -> Dict[str, Any]:
    """Reads a JSON hook payload from stdin. Returns {} when absent or a TTY."""
    stream = stream or sys.stdin
    raw = ""
    try:
        if stream is not None and not stream.isatty():
            raw = stream.read().strip()
    except Exception:
        raw = ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"raw": data}
    except Exception:
        return {"raw": raw}


def detect_harness(payload: Dict[str, Any], requested: str = HARNESS_AUTO) -> str:
    """Resolves the harness dialect. Claude Code payloads carry hook_event_name."""
    if requested in (HARNESS_CLAUDE, HARNESS_LEGACY):
        return requested
    if isinstance(payload, dict) and "hook_event_name" in payload:
        return HARNESS_CLAUDE
    return HARNESS_LEGACY


def guard_response(allowed: bool, reason: str, harness: str) -> Dict[str, Any]:
    """Returns {"stdout": str, "stderr": str, "exit_code": int} for a PreToolUse decision."""
    if harness == HARNESS_CLAUDE:
        if allowed:
            return {"stdout": "", "stderr": "", "exit_code": 0}
        body = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        return {"stdout": json.dumps(body), "stderr": f"[BAND PRE-TOOL GATE] {reason}\n", "exit_code": 2}

    if allowed:
        return {"stdout": json.dumps({"decision": "allow"}), "stderr": "", "exit_code": 0}
    body = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        "decision": "deny",
        "reason": reason,
    }
    return {"stdout": json.dumps(body, indent=2), "stderr": f"\n[BAND PRE-TOOL GATE] {reason}\n", "exit_code": 2}


def stop_response(result: Dict[str, Any], harness: str) -> Dict[str, Any]:
    """
    Translates a Band FSM result ({"decision": "allow"|"continue", "reason"}) into
    the harness' Stop-hook contract.
    """
    decision = result.get("decision", "allow")
    reason = result.get("reason") or result.get("message") or ""

    if harness != HARNESS_CLAUDE:
        return {"stdout": json.dumps(result), "stderr": "", "exit_code": 0}

    if decision in ("continue", "block"):
        body = {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "decision": "continue",
                "reason": reason,
            }
        }
        return {"stdout": json.dumps(body), "stderr": reason + "\n", "exit_code": 2}

    if decision == "error":
        # Never trap the agent in a loop because Band itself is broken.
        body = {"systemMessage": f"Band Stop hook error (stop allowed): {reason}"}
        return {"stdout": json.dumps(body), "stderr": reason + "\n", "exit_code": 0}

    return {"stdout": "", "stderr": "", "exit_code": 0}


def emit(response: Dict[str, Any]) -> None:
    """Writes a response produced by guard_response/stop_response and exits."""
    if response.get("stderr"):
        sys.stderr.write(response["stderr"])
    if response.get("stdout"):
        print(response["stdout"])
    sys.stdout.flush()
    sys.exit(response.get("exit_code", 0))

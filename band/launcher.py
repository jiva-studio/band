"""Launcher and hook-command definitions shared by setup, doctor and the CLI.

Band lives in ``.agents/band`` inside a target repository, so a bare
``python3 -m band`` run from the repository root cannot import it, and on
some machines (e.g. NixOS) ``python3`` is not on PATH at all. The launcher
script ``.agents/bin/band`` solves both problems: it puts ``.agents`` on
PYTHONPATH relative to its own location and picks an interpreter in this
order: ``$BAND_PYTHON``, ``python3``, ``python`` (if >= 3.8), then
``uv run --no-project python``.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

# Relative path of the launcher inside a repository that has Band installed.
LAUNCHER_REL_PATH = ".agents/bin/band"

# Command used in docs, skills and interactive shells (run from the repo root).
BAND_CMD = "sh .agents/bin/band"

# Commands for Claude Code (.agents/settings.json, seen as .claude/settings.json via the symlink). Claude Code exports
# CLAUDE_PROJECT_DIR to hook processes, so the hook works from any cwd.
CLAUDE_GUARD_COMMAND = 'sh "${CLAUDE_PROJECT_DIR}/.agents/bin/band" --guard --harness claude-code'
CLAUDE_STOP_COMMAND = 'sh "${CLAUDE_PROJECT_DIR}/.agents/bin/band" --hook --harness claude-code'

# Claude Code tool names that can modify files or run shell commands.
CLAUDE_GUARD_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash"

# Commands for other harnesses (.agents/hooks.json, run from repo root).
LEGACY_GUARD_COMMAND = f"{BAND_CMD} --guard"
LEGACY_STOP_COMMAND = f"{BAND_CMD} --hook"
LEGACY_GUARD_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|write_to_file|replace_file_content|edit_file|Bash|run_command|bash"

MIN_PYTHON = (3, 8)

LAUNCHER_SCRIPT = """#!/bin/sh
# Band launcher - runs `python -m band` with .agents/ on PYTHONPATH.
# Interpreter order: $BAND_PYTHON, python3, python (>= 3.8), `uv run --no-project python`.
# Invoke as: sh .agents/bin/band <args>   (works from any directory)
SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
AGENTS_DIR=$(dirname -- "$SELF_DIR")
PYTHONPATH="$AGENTS_DIR${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

if [ -n "${BAND_PYTHON:-}" ]; then
  # Intentionally unquoted so BAND_PYTHON may contain arguments (e.g. "uv run python").
  exec $BAND_PYTHON -m band "$@"
fi

for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    exec "$py" -m band "$@"
  fi
done

if command -v uv >/dev/null 2>&1; then
  exec uv run --no-project --quiet python -m band "$@"
fi

echo "band: no Python >= 3.8 interpreter found. Set BAND_PYTHON, or install python3 or uv." >&2
exit 127
"""


def write_launcher(repo_root: Path) -> bool:
    """Writes .agents/bin/band if missing or outdated. Returns True if written."""
    target = repo_root / LAUNCHER_REL_PATH
    if target.exists() and target.read_text(encoding="utf-8") == LAUNCHER_SCRIPT:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(LAUNCHER_SCRIPT, encoding="utf-8")
    try:
        target.chmod(0o755)
    except OSError:
        pass
    return True


def _python_ok(cmd: List[str]) -> bool:
    try:
        res = subprocess.run(
            cmd + ["-c", "import sys; sys.exit(sys.version_info < (%d, %d))" % MIN_PYTHON],
            capture_output=True,
            timeout=60,
        )
        return res.returncode == 0
    except Exception:
        return False


def resolve_interpreter(env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    """Mirrors the launcher's interpreter selection. Returns {"source", "command"} or None."""
    env = os.environ if env is None else env
    band_python = env.get("BAND_PYTHON")
    if band_python:
        return {"source": "BAND_PYTHON", "command": band_python}
    for py in ("python3", "python"):
        path = shutil.which(py, path=env.get("PATH"))
        if path and _python_ok([path]):
            return {"source": py, "command": path}
    uv = shutil.which("uv", path=env.get("PATH"))
    if uv:
        return {"source": "uv", "command": f"{uv} run --no-project python"}
    return None

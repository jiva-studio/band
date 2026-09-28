import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple
from band.config import REPO_ROOT
from band.setup import detect_project_stack, claude_settings_has_band_hooks
from band.launcher import BAND_CMD, LAUNCHER_REL_PATH, resolve_interpreter

# Works before the launcher exists (from the repo root, with any Python 3.8+).
BAND_CMD_BOOTSTRAP = "PYTHONPATH=.agents python3 -m band"
BAND_CMD_BOOTSTRAP_UV = "PYTHONPATH=.agents uv run --no-project python -m band"


def check_git_capability(repo_root: Path) -> Dict[str, Any]:
    """Checks git installation and worktree capability."""
    try:
        res = subprocess.run(["git", "--version"], capture_output=True, text=True, cwd=repo_root)
        if res.returncode != 0:
            return {"status": "FAIL", "message": "Git is not installed or not working.", "tip": "Install Git >= 2.20"}

        version_str = res.stdout.strip()
        res_wt = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True, cwd=repo_root)
        if res_wt.returncode == 0:
            return {"status": "OK", "message": f"{version_str} (Worktree enabled)"}
        else:
            return {"status": "WARN", "message": f"{version_str} (Worktrees unsupported in current repo state)"}
    except Exception as e:
        return {"status": "FAIL", "message": f"Git error: {str(e)}", "tip": "Install Git >= 2.20"}


def check_makefile(repo_root: Path) -> Dict[str, Any]:
    """Checks if repository provides declarative verification targets."""
    makefile = repo_root / "Makefile"
    if not makefile.exists():
        return {
            "status": "WARN",
            "message": "Makefile not found.",
            "tip": "Run /band-install to let the agent discover and configure verification targets for your project."
        }

    content = makefile.read_text(encoding="utf-8")
    has_test = "check-package:" in content or "test-package:" in content or "test:" in content
    has_mutate = "mutate-diff:" in content or "mutate:" in content
    has_setup = "setup:" in content or "prepare:" in content

    missing = []
    if not has_test:
        missing.append("check-package (or test)")
    if not has_mutate:
        missing.append("mutate-diff")
    if not has_setup:
        missing.append("setup")

    if not missing:
        return {"status": "OK", "message": "Makefile configured with test, mutate-diff, and setup targets."}
    else:
        return {
            "status": "WARN",
            "message": f"Makefile missing targets: {', '.join(missing)}.",
            "tip": "Run /band-install to configure project-specific targets."
        }


def check_mutation_engine(repo_root: Path) -> Dict[str, Any]:
    """Checks if mutation testing is configured or available."""
    makefile = repo_root / "Makefile"
    if makefile.exists() and "mutate-diff:" in makefile.read_text(encoding="utf-8"):
        return {"status": "OK", "message": "Declarative mutate-diff target configured in Makefile."}

    # Check common configuration files
    if any((repo_root / name).exists() for name in ["stryker.config.json", "stryker.config.mjs", "stryker.config.js", "mutmut.ini", "mutants.toml"]):
        return {"status": "OK", "message": "Mutation testing configuration file detected in repository."}

    # Fallback to Critic review
    return {
        "status": "INFO",
        "message": "No dedicated mutate-diff target configured (L3 Critic Agent will perform virtual mutant audits).",
        "tip": "Run /band-install to configure native mutation testing for your stack."
    }


def check_interpreter(repo_root: Path) -> Dict[str, Any]:
    """Checks that the .agents/bin/band launcher exists and can find a Python >= 3.8."""
    launcher = repo_root / LAUNCHER_REL_PATH
    interp = resolve_interpreter()
    if not interp:
        return {
            "status": "FAIL",
            "message": "No Python >= 3.8 found for hooks (tried $BAND_PYTHON, python3, python, uv).",
            "tip": "Install python3 or uv, or export BAND_PYTHON=/path/to/python3."
        }
    note = ""
    if interp["source"] == "uv":
        note = " (python3 not on PATH; launcher falls back to uv)"
    if not launcher.exists():
        return {
            "status": "WARN",
            "message": f"Interpreter: {interp['command']}{note}, but launcher {LAUNCHER_REL_PATH} is missing.",
            "tip": f"Run '{BAND_CMD_BOOTSTRAP} --init' (without python3: '{BAND_CMD_BOOTSTRAP_UV} --init') to write the launcher and hooks."
        }
    return {"status": "OK", "message": f"Launcher {LAUNCHER_REL_PATH} -> {interp['command']}{note}"}


def check_claude_hooks(repo_root: Path) -> Dict[str, Any]:
    """Checks that Band's hooks are wired into Claude Code's .claude/settings.json."""
    settings_file = repo_root / ".claude" / "settings.json"
    if not settings_file.exists():
        return {
            "status": "WARN",
            "message": ".claude/settings.json not found; Claude Code will not run Band hooks.",
            "tip": f"Run '{BAND_CMD} --init' to merge Band hooks into .claude/settings.json."
        }
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8") or "{}")
    except Exception as e:
        return {"status": "FAIL", "message": f"Invalid .claude/settings.json: {str(e)}"}
    found = claude_settings_has_band_hooks(data)
    missing = [ev for ev, ok in found.items() if not ok]
    if not missing:
        return {"status": "OK", "message": "PreToolUse Guard & Stop Hook registered in .claude/settings.json."}
    return {
        "status": "WARN",
        "message": f"Band hooks missing in .claude/settings.json: {', '.join(missing)}.",
        "tip": f"Run '{BAND_CMD} --init' to merge Band hooks into .claude/settings.json."
    }


def check_hooks(repo_root: Path) -> Dict[str, Any]:
    """Checks if Band verification hooks and PreToolUse gates are wired."""
    hooks_file = repo_root / ".agents" / "hooks.json"
    if not hooks_file.exists():
        hooks_file = repo_root / "hooks.json"

    if not hooks_file.exists():
        return {
            "status": "WARN",
            "message": "Hooks configuration (.agents/hooks.json) not found.",
            "tip": f"Run '{BAND_CMD} --init' or '/band-install' to register Stop and PreToolUse hooks."
        }

    try:
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        gate = data.get("deterministic-done-gate", data)
        has_pre = bool(gate.get("PreToolUse"))
        has_stop = bool(gate.get("Stop"))
        if has_pre and has_stop:
            return {"status": "OK", "message": "PreToolUse Guard & Stop Hook registered in hooks.json."}
        else:
            return {"status": "WARN", "message": "Partial hooks configured.", "tip": "Ensure PreToolUse and Stop hooks are present."}
    except Exception as e:
        return {"status": "FAIL", "message": f"Invalid hooks.json format: {str(e)}"}


def check_worktree_include(repo_root: Path) -> Dict[str, Any]:
    """Checks .worktreeinclude file for untracked config management."""
    wt_inc = repo_root / ".worktreeinclude"
    if wt_inc.exists():
        entries = [l.strip() for l in wt_inc.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        return {"status": "OK", "message": f".worktreeinclude found with {len(entries)} pattern(s)."}
    else:
        return {
            "status": "INFO",
            "message": ".worktreeinclude not present (defaulting to standard .env copying).",
            "tip": "Create .worktreeinclude to declare untracked files to copy into worktrees."
        }


def run_doctor(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """Runs complete environment diagnostics."""
    stack = detect_project_stack(repo_root)

    checks = {
        "git": check_git_capability(repo_root),
        "stack": {
            "status": "OK",
            "message": f"Detected Project Indicators: {stack['language'].capitalize()} | Manifests: {', '.join(stack['config_files']) or 'None'}"
        },
        "makefile": check_makefile(repo_root),
        "mutation": check_mutation_engine(repo_root),
        "interpreter": check_interpreter(repo_root),
        "hooks": check_hooks(repo_root),
        "claude_hooks": check_claude_hooks(repo_root),
        "worktree": check_worktree_include(repo_root),
    }

    all_ok = all(c["status"] in ("OK", "INFO") for c in checks.values())

    return {
        "ready": all_ok,
        "repo_root": str(repo_root),
        "stack": stack,
        "checks": checks
    }


def format_doctor_report(diag: Dict[str, Any]) -> str:
    """Formats the diagnostic report into user-friendly terminal output."""
    lines = [
        "🥁 Band Environment Doctor & Health Check",
        "=" * 60,
    ]

    status_icons = {
        "OK": "✅ [OK]  ",
        "WARN": "⚠️ [WARN]",
        "FAIL": "❌ [FAIL]",
        "INFO": "💡 [INFO]",
    }

    for name, item in diag["checks"].items():
        icon = status_icons.get(item["status"], "• ")
        lines.append(f"{icon} {name.upper()}: {item['message']}")
        if "tip" in item:
            lines.append(f"         👉 Recommendation: {item['tip']}")

    lines.append("=" * 60)
    if diag["ready"]:
        lines.append("🎉 Result: Environment is 100% READY for verified task execution!")
    else:
        lines.append("⚠️ Result: Some components need configuration. Run '/band-install' to configure.")

    return "\n".join(lines)

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple
from band.config import REPO_ROOT
from band.setup import detect_project_stack


def check_git_capability(repo_root: Path) -> Dict[str, Any]:
    """Checks git installation and worktree capability."""
    try:
        res = subprocess.run(["git", "--version"], capture_output=True, text=True, cwd=repo_root)
        if res.returncode != 0:
            return {"status": "FAIL", "message": "Git is not installed or not working.", "tip": "Install Git >= 2.20"}

        version_str = res.stdout.strip()
        # Test worktree capability
        res_wt = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True, cwd=repo_root)
        if res_wt.returncode == 0:
            return {"status": "OK", "message": f"{version_str} (Worktree enabled)"}
        else:
            return {"status": "WARN", "message": f"{version_str} (Worktrees unsupported in current repo state)"}
    except Exception as e:
        return {"status": "FAIL", "message": f"Git error: {str(e)}", "tip": "Install Git >= 2.20"}


def check_makefile(repo_root: Path, stack: Dict[str, Any]) -> Dict[str, Any]:
    """Checks Makefile targets for verification harness."""
    makefile = repo_root / "Makefile"
    if not makefile.exists():
        return {
            "status": "WARN",
            "message": "Makefile not found.",
            "tip": "Run 'python3 -m band --init' to generate standard targets."
        }

    content = makefile.read_text(encoding="utf-8")
    has_test = "check-package:" in content or "test-package:" in content or "test:" in content
    has_mutate = "mutate-diff:" in content or "mutate:" in content
    has_setup = "setup:" in content or "prepare:" in content

    missing = []
    if not has_test:
        missing.append("check-package")
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
            "tip": "Run 'python3 -m band --init' to append standard verification targets."
        }


def check_mutation_engine(repo_root: Path, stack: Dict[str, Any]) -> Dict[str, Any]:
    """Checks mutation testing engine status and availability."""
    lang = stack.get("language")

    if lang in ("typescript", "javascript"):
        if (repo_root / "stryker.config.json").exists() or (repo_root / "stryker.config.mjs").exists():
            return {"status": "OK", "message": "Stryker Mutator configured (stryker.config.json)."}
        if shutil.which("npx"):
            return {
                "status": "OK",
                "message": "Zero-install on-demand Stryker available via 'npx @stryker-mutator/core'.",
                "tip": "To install locally for faster runs: pnpm add -D @stryker-mutator/core"
            }
        return {"status": "WARN", "message": "No mutation tool configured.", "tip": "Install Stryker or run band --init"}

    elif lang == "python":
        if (repo_root / "mutmut.ini").exists() or (repo_root / "pyproject.toml").exists():
            return {"status": "OK", "message": "Python mutation runner configured."}
        if shutil.which("uvx"):
            return {
                "status": "OK",
                "message": "Zero-install on-demand Mutmut available via 'uvx mutmut'.",
                "tip": "To install locally: uv add --dev mutmut"
            }
        return {"status": "WARN", "message": "Python mutmut not configured.", "tip": "Run 'uv add --dev mutmut' or 'band --init'"}

    elif lang == "rust":
        if shutil.which("cargo-mutants"):
            return {"status": "OK", "message": "cargo-mutants installed in PATH."}
        return {"status": "INFO", "message": "cargo-mutants available via 'cargo install cargo-mutants'."}

    return {"status": "INFO", "message": "Generic/Critic mutation analysis active."}


def check_hooks(repo_root: Path) -> Dict[str, Any]:
    """Checks if Band verification hooks and PreToolUse gates are wired."""
    hooks_file = repo_root / ".agents" / "hooks.json"
    if not hooks_file.exists():
        hooks_file = repo_root / "hooks.json"

    if not hooks_file.exists():
        return {
            "status": "WARN",
            "message": "Hooks configuration (.agents/hooks.json) not found.",
            "tip": "Run 'python3 -m band --init' to register Stop and PreToolUse hooks."
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
            "message": f"Language: {stack['language'].capitalize()} | Package Manager: {stack['package_manager']} | Runner: {stack['test_runner']}"
        },
        "makefile": check_makefile(repo_root, stack),
        "mutation": check_mutation_engine(repo_root, stack),
        "hooks": check_hooks(repo_root),
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
        lines.append("⚠️ Result: Some components need configuration. Run 'python3 -m band --init' to configure.")

    return "\n".join(lines)

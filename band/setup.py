import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from band.config import REPO_ROOT


def detect_project_stack(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """Lightweight discovery of project indicators (language, build files, env files)."""
    stack: Dict[str, Any] = {
        "language": "generic",
        "build_system": "makefile" if (repo_root / "Makefile").exists() else "unknown",
        "has_makefile": (repo_root / "Makefile").exists(),
        "env_files": [],
        "config_files": [],
    }

    # Discover build/project manifests
    if (repo_root / "package.json").exists():
        stack["language"] = "typescript" if (repo_root / "tsconfig.json").exists() else "javascript"
        stack["config_files"].append("package.json")
    elif (repo_root / "pyproject.toml").exists() or (repo_root / "requirements.txt").exists() or (repo_root / "setup.py").exists():
        stack["language"] = "python"
        stack["config_files"].extend([f.name for f in [repo_root / "pyproject.toml", repo_root / "requirements.txt"] if f.exists()])
    elif (repo_root / "Cargo.toml").exists():
        stack["language"] = "rust"
        stack["config_files"].append("Cargo.toml")
    elif (repo_root / "go.mod").exists():
        stack["language"] = "go"
        stack["config_files"].append("go.mod")

    # Discover env files
    for item in repo_root.glob(".env*"):
        if item.is_file():
            stack["env_files"].append(item.name)

    return stack


def setup_project(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """
    Initializes standard Band plumbing (.agents/hooks.json, .worktreeinclude,
    and base Makefile skeleton if missing).
    """
    stack = detect_project_stack(repo_root)
    actions_taken: List[str] = []

    # 1. Ensure .agents directory & hooks.json
    agents_dir = repo_root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    hooks_file = agents_dir / "hooks.json"
    if not hooks_file.exists():
        base_hooks = {
            "deterministic-done-gate": {
                "enabled": True,
                "PreToolUse": [
                    {
                        "matcher": "Edit|Write|write_to_file|replace_file_content|edit_file|Bash|run_command|bash",
                        "type": "command",
                        "command": "python3 -m band --guard",
                        "timeout": 30
                    }
                ],
                "Stop": [
                    {
                        "type": "command",
                        "command": "python3 -m band --hook",
                        "timeout": 120
                    }
                ]
            }
        }
        hooks_file.write_text(json.dumps(base_hooks, indent=2), encoding="utf-8")
        actions_taken.append("Created .agents/hooks.json")

    # 2. Setup .worktreeinclude
    wt_inc = repo_root / ".worktreeinclude"
    if not wt_inc.exists():
        inc_lines = ["# Untracked files to copy into new Git Worktrees", ".env", ".env.local", ".env.development"]
        for env_f in stack.get("env_files", []):
            if env_f not in inc_lines:
                inc_lines.append(env_f)
        wt_inc.write_text("\n".join(inc_lines) + "\n", encoding="utf-8")
        actions_taken.append("Created .worktreeinclude")

    # 3. Ensure .agents/worktrees/ in .gitignore
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        git_content = gitignore.read_text(encoding="utf-8")
        if ".agents/worktrees/" not in git_content:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write("\n# Band isolated task worktrees\n.agents/worktrees/\n")
            actions_taken.append("Added .agents/worktrees/ to .gitignore")
    else:
        gitignore.write_text(".agents/worktrees/\n", encoding="utf-8")
        actions_taken.append("Created .gitignore with .agents/worktrees/")

    return {
        "stack": stack,
        "actions_taken": actions_taken,
        "repo_root": str(repo_root),
    }

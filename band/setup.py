import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from band.config import REPO_ROOT


def detect_project_stack(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """Inspects a repository and determines language, test runner, package manager, and env files."""
    stack: Dict[str, Any] = {
        "language": "unknown",
        "package_manager": "unknown",
        "test_runner": "unknown",
        "has_makefile": (repo_root / "Makefile").exists(),
        "has_mutation": False,
        "mutation_tool": "none",
        "env_files": [],
        "source_dirs": [],
    }

    # 1. Detect Node / TypeScript
    pkg_json = repo_root / "package.json"
    if pkg_json.exists():
        stack["language"] = "typescript" if (repo_root / "tsconfig.json").exists() else "javascript"
        try:
            pdata = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = {**pdata.get("dependencies", {}), **pdata.get("devDependencies", {})}

            # Package manager
            if (repo_root / "pnpm-lock.yaml").exists() or (repo_root / "pnpm-workspace.yaml").exists():
                stack["package_manager"] = "pnpm"
            elif (repo_root / "yarn.lock").exists():
                stack["package_manager"] = "yarn"
            elif (repo_root / "bun.lockb").exists() or (repo_root / "bun.lock").exists():
                stack["package_manager"] = "bun"
            else:
                stack["package_manager"] = "npm"

            # Test runner
            if "vitest" in deps:
                stack["test_runner"] = "vitest"
            elif "jest" in deps:
                stack["test_runner"] = "jest"
            elif "mocha" in deps:
                stack["test_runner"] = "mocha"

            # Mutation
            if "@stryker-mutator/core" in deps or (repo_root / "stryker.config.json").exists() or (repo_root / "stryker.config.mjs").exists():
                stack["has_mutation"] = True
                stack["mutation_tool"] = "stryker"
        except Exception:
            pass

    # 2. Detect Python
    elif (
        (repo_root / "pyproject.toml").exists()
        or (repo_root / "requirements.txt").exists()
        or (repo_root / "setup.py").exists()
        or any(repo_root.glob("*.py"))
        or any((p / "__init__.py").exists() for p in repo_root.iterdir() if p.is_dir() and not p.name.startswith("."))
    ):
        stack["language"] = "python"
        if (repo_root / "uv.lock").exists() or shutil.which("uv"):
            stack["package_manager"] = "uv"
        elif (repo_root / "poetry.lock").exists():
            stack["package_manager"] = "poetry"
        elif (repo_root / "Pipfile").exists():
            stack["package_manager"] = "pipenv"
        else:
            stack["package_manager"] = "pip"

        stack["test_runner"] = "pytest"

        if (repo_root / "mutmut.ini").exists() or (repo_root / "setup.cfg").exists():
            stack["has_mutation"] = True
            stack["mutation_tool"] = "mutmut"

    # 3. Detect Rust
    elif (repo_root / "Cargo.toml").exists():
        stack["language"] = "rust"
        stack["package_manager"] = "cargo"
        stack["test_runner"] = "cargo test"
        if (repo_root / "mutants.toml").exists():
            stack["has_mutation"] = True
            stack["mutation_tool"] = "cargo-mutants"

    # 4. Detect Go
    elif (repo_root / "go.mod").exists():
        stack["language"] = "go"
        stack["package_manager"] = "go"
        stack["test_runner"] = "go test"

    # 5. Detect env / untracked config files
    for item in repo_root.glob(".env*"):
        if item.is_file():
            stack["env_files"].append(item.name)

    return stack


def generate_makefile_targets(stack: Dict[str, Any]) -> str:
    """Generates standard Makefile targets tailored to the detected stack."""
    lang = stack.get("language")
    pm = stack.get("package_manager", "npm")
    runner = stack.get("test_runner", "test")

    targets = []

    # setup target
    if lang in ("typescript", "javascript"):
        if pm == "pnpm":
            targets.append("setup:\n\t@pnpm install --prefer-offline\n")
        elif pm == "yarn":
            targets.append("setup:\n\t@yarn install\n")
        elif pm == "bun":
            targets.append("setup:\n\t@bun install\n")
        else:
            targets.append("setup:\n\t@npm install\n")

        # check-package / test target
        if runner == "vitest":
            targets.append("check-package:\n\t@npx vitest run $(if $(PKG),$(PKG),)\n")
            targets.append("test-package:\n\t@npx vitest run $(if $(PKG),$(PKG),)\n")
        elif runner == "jest":
            targets.append("check-package:\n\t@npx jest $(if $(PKG),$(PKG),)\n")
            targets.append("test-package:\n\t@npx jest $(if $(PKG),$(PKG),)\n")
        else:
            targets.append(f"check-package:\n\t@{pm} test\n")
            targets.append(f"test-package:\n\t@{pm} test\n")

        # mutate-diff target
        targets.append("mutate-diff:\n\t@npx -y @stryker-mutator/core run --reporters json --diff\n")

    elif lang == "python":
        if pm == "uv":
            targets.append("setup:\n\t@uv sync\n")
            targets.append("check-package:\n\t@uv run pytest $(if $(PKG),$(PKG),tests)\n")
            targets.append("test-package:\n\t@uv run pytest $(if $(PKG),$(PKG),tests)\n")
            targets.append("mutate-diff:\n\t@uvx mutmut run --paths-to-mutate $(if $(PKG),$(PKG),.)\n")
        else:
            targets.append("setup:\n\t@pip install -r requirements.txt\n")
            targets.append("check-package:\n\t@pytest $(if $(PKG),$(PKG),tests)\n")
            targets.append("test-package:\n\t@pytest $(if $(PKG),$(PKG),tests)\n")
            targets.append("mutate-diff:\n\t@mutmut run --paths-to-mutate $(if $(PKG),$(PKG),.)\n")

    elif lang == "rust":
        targets.append("setup:\n\t@cargo check\n")
        targets.append("check-package:\n\t@cargo test $(if $(PKG),-p $(PKG),)\n")
        targets.append("test-package:\n\t@cargo test $(if $(PKG),-p $(PKG),)\n")
        targets.append("mutate-diff:\n\t@cargo mutants --in-diff\n")

    elif lang == "go":
        targets.append("setup:\n\t@go mod download\n")
        targets.append("check-package:\n\t@go test $(if $(PKG),./$(PKG)/...,./...)\n")
        targets.append("test-package:\n\t@go test $(if $(PKG),./$(PKG)/...,./...)\n")
        targets.append("mutate-diff:\n\t@go test -v ./...\n")

    else:
        targets.append("check-package:\n\t@echo 'Run test suite' && exit 0\n")
        targets.append("test-package:\n\t@echo 'Run test suite' && exit 0\n")

    return "\n".join(targets)


def generate_stryker_config(stack: Dict[str, Any]) -> str:
    """Generates minimal Stryker configuration for TypeScript/JavaScript."""
    runner = stack.get("test_runner", "vitest")
    if runner == "vitest":
        return json.dumps({
            "$schema": "./node_modules/@stryker-mutator/core/schema/stryker-schema.json",
            "testRunner": "vitest",
            "reporters": ["json", "clear-text"],
            "coverageAnalysis": "perTest",
            "checkers": ["typescript"],
            "tsconfigFile": "tsconfig.json"
        }, indent=2)
    else:
        return json.dumps({
            "$schema": "./node_modules/@stryker-mutator/core/schema/stryker-schema.json",
            "testRunner": "jest",
            "reporters": ["json", "clear-text"],
            "coverageAnalysis": "perTest",
            "checkers": ["typescript"],
            "tsconfigFile": "tsconfig.json"
        }, indent=2)


def setup_project(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """
    Auto-scaffolds Makefile targets, mutation config, .worktreeinclude,
    and .agents directory for a repository.
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

    # 3. Setup Makefile
    makefile = repo_root / "Makefile"
    new_targets = generate_makefile_targets(stack)
    if not makefile.exists():
        makefile.write_text(f"# Generated by Band Harness\n.PHONY: setup check-package test-package mutate-diff\n\n{new_targets}", encoding="utf-8")
        actions_taken.append("Created Makefile with test and mutation targets")
    else:
        content = makefile.read_text(encoding="utf-8")
        needed_targets = []
        if "check-package:" not in content and "test-package:" not in content:
            needed_targets.append("check-package")
        if "mutate-diff:" not in content:
            needed_targets.append("mutate-diff")
        if "setup:" not in content:
            needed_targets.append("setup")

        if needed_targets:
            with open(makefile, "a", encoding="utf-8") as f:
                f.write(f"\n\n# Added by Band for verification harness\n{new_targets}")
            actions_taken.append(f"Appended targets to Makefile: {', '.join(needed_targets)}")

    # 4. Setup Stryker config for TS/JS if applicable
    if stack["language"] in ("typescript", "javascript"):
        stryker_cfg = repo_root / "stryker.config.json"
        if not stryker_cfg.exists():
            stryker_cfg.write_text(generate_stryker_config(stack), encoding="utf-8")
            actions_taken.append("Created stryker.config.json for diff mutation testing")

    # 5. Ensure .agents/worktrees/ in .gitignore
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

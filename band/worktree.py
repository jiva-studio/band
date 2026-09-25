import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from band.config import REPO_ROOT, TASKS_DIR

WORKTREES_BASE_DIR = REPO_ROOT / ".agents" / "worktrees"


def _run_cmd(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    """Runs a shell command and returns (returncode, stdout, stderr)."""
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def ensure_worktrees_ignored(repo_root: Path = REPO_ROOT) -> None:
    """Ensures .agents/worktrees is in .gitignore so main working tree stays clean."""
    gitignore = repo_root / ".gitignore"
    pattern = ".agents/worktrees/"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if pattern not in content:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write(f"\n# Band isolated task worktrees\n{pattern}\n")
    else:
        gitignore.write_text(f"# Band isolated task worktrees\n{pattern}\n", encoding="utf-8")


def copy_worktree_includes(repo_root: Path, worktree_dir: Path) -> List[str]:
    """
    Copies untracked files declared in .worktreeinclude or .agents/worktreeinclude
    into the newly created worktree.
    """
    include_files = [
        repo_root / ".worktreeinclude",
        repo_root / ".agents" / "worktreeinclude",
    ]
    patterns: List[str] = []
    for inc in include_files:
        if inc.exists():
            for line in inc.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)

    copied = []
    for pattern in patterns:
        source_path = repo_root / pattern
        dest_path = worktree_dir / pattern
        if source_path.is_file():
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)
            copied.append(pattern)
        elif source_path.is_dir():
            if not dest_path.exists():
                shutil.copytree(source_path, dest_path)
                copied.append(pattern)

    return copied


def run_worktree_create_hook(worktree_dir: Path, repo_root: Path = REPO_ROOT) -> None:
    """Executes the WorktreeCreate lifecycle hook if defined in hooks.json."""
    hooks_files = [
        repo_root / "hooks.json",
        repo_root / ".agents" / "hooks.json",
    ]
    for hf in hooks_files:
        if hf.exists():
            try:
                data = json.loads(hf.read_text(encoding="utf-8"))
                worktree_hooks = data.get("WorktreeCreate", [])
                if isinstance(worktree_hooks, list):
                    for hook in worktree_hooks:
                        cmd = hook.get("command")
                        if cmd:
                            timeout = hook.get("timeout", 120)
                            subprocess.run(cmd, cwd=worktree_dir, shell=True, timeout=timeout)
            except Exception as e:
                print(f"Warning: Failed to execute WorktreeCreate hook: {e}", file=sys.stderr)


def create_worktree(
    spec_slug: str,
    intent_slug: Optional[str] = None,
    repo_root: Path = REPO_ROOT
) -> Tuple[bool, Path, str]:
    """
    Creates an isolated Git worktree and branch for a spec/task.
    Copies intent.md into the worktree task directory.
    Returns (success, worktree_path, message).
    """
    ensure_worktrees_ignored(repo_root)
    worktrees_base = repo_root / ".agents" / "worktrees"
    worktrees_base.mkdir(parents=True, exist_ok=True)

    branch_name = f"task/{spec_slug}"
    worktree_path = (worktrees_base / spec_slug).resolve()

    # 1. Check if worktree directory already exists
    if worktree_path.exists():
        # Check if it's an existing valid worktree
        code, out, _ = _run_cmd(["git", "worktree", "list", "--porcelain"], repo_root)
        if str(worktree_path) in out:
            return True, worktree_path, f"Existing worktree re-attached at {worktree_path}"

    # 2. Check if branch already exists
    code, out, _ = _run_cmd(["git", "branch", "--list", branch_name], repo_root)
    branch_exists = bool(out.strip())

    if branch_exists:
        cmd = ["git", "worktree", "add", str(worktree_path), branch_name]
    else:
        cmd = ["git", "worktree", "add", str(worktree_path), "-b", branch_name]

    code, out, err = _run_cmd(cmd, repo_root)
    if code != 0:
        return False, worktree_path, f"Failed to create git worktree: {err or out}"

    # 3. Setup task directory inside worktree
    worktree_task_dir = worktree_path / ".agents" / "tasks" / spec_slug
    worktree_task_dir.mkdir(parents=True, exist_ok=True)
    (worktree_task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (worktree_task_dir / "scratch").mkdir(parents=True, exist_ok=True)

    # 4. Copy intent.md from main repo if available
    effective_intent_slug = intent_slug or spec_slug
    main_intent_file = repo_root / ".agents" / "tasks" / effective_intent_slug / "intent.md"
    if not main_intent_file.exists():
        main_intent_file = TASKS_DIR / effective_intent_slug / "intent.md"

    if main_intent_file.exists():
        dest_intent = worktree_task_dir / "intent.md"
        shutil.copy2(main_intent_file, dest_intent)

    # 5. Copy untracked config files (.worktreeinclude)
    copy_worktree_includes(repo_root, worktree_path)

    # 6. Run WorktreeCreate hook if defined
    run_worktree_create_hook(worktree_path, repo_root)

    return True, worktree_path, f"Created isolated worktree on branch '{branch_name}' at {worktree_path}"


def merge_worktree(
    spec_slug: str,
    target_branch: str = "main",
    repo_root: Path = REPO_ROOT
) -> Tuple[bool, str]:
    """Merges a task branch into target_branch from main repository root."""
    branch_name = f"task/{spec_slug}"
    code, out, err = _run_cmd(["git", "checkout", target_branch], repo_root)
    if code != 0:
        return False, f"Failed to checkout {target_branch}: {err or out}"

    code, out, err = _run_cmd(["git", "merge", "--no-ff", branch_name, "-m", f"feat({spec_slug}): completed verified task via Band"], repo_root)
    if code != 0:
        return False, f"Merge conflict or error while merging {branch_name} into {target_branch}: {err or out}"

    return True, f"Successfully merged {branch_name} into {target_branch}."


def remove_worktree(
    spec_slug: str,
    delete_branch: bool = False,
    repo_root: Path = REPO_ROOT
) -> Tuple[bool, str]:
    """Safely removes a worktree and optionally deletes its task branch."""
    worktrees_base = repo_root / ".agents" / "worktrees"
    worktree_path = (worktrees_base / spec_slug).resolve()
    branch_name = f"task/{spec_slug}"

    if worktree_path.exists():
        code, out, err = _run_cmd(["git", "worktree", "remove", "--force", str(worktree_path)], repo_root)
        if code != 0:
            # Fallback manual removal if worktree is orphaned
            shutil.rmtree(worktree_path, ignore_errors=True)
            _run_cmd(["git", "worktree", "prune"], repo_root)

    if delete_branch:
        _run_cmd(["git", "branch", "-d", branch_name], repo_root)

    return True, f"Cleaned up worktree for '{spec_slug}'."

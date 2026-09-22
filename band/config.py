import os
import subprocess
from pathlib import Path
from typing import Optional


def _is_repo_root(path: Path) -> bool:
    """Checks if a directory is a valid repository root (has .git or Makefile)."""
    return path.is_dir() and ((path / ".git").exists() or (path / "Makefile").exists())


def _find_source_in_dir(parent_dir: Path) -> Optional[Path]:
    """Finds a child repository under a 'source/' directory."""
    source_dir = parent_dir / "source"
    if not source_dir.is_dir():
        return None
    for child in sorted(source_dir.iterdir()):
        if _is_repo_root(child):
            return child
    return None


def _find_repo_root() -> Path:
    # 1. Explicit environment override
    if env_root := os.getenv("BAND_REPO_ROOT"):
        p = Path(env_root).resolve()
        if p.exists():
            return p

    # 2. Git top level of current working directory
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=True
        )
        if (top := Path(res.stdout.strip())).exists() and _is_repo_root(top):
            return top
    except Exception:
        pass

    # 3. Search upwards from cwd and module path for repo or multi-repo source layout
    for start in [Path.cwd(), Path(__file__).resolve().parent]:
        for current in [start, *start.parents]:
            if _is_repo_root(current):
                return current
            if sibling_repo := _find_source_in_dir(current):
                return sibling_repo
            if sibling_repo := _find_source_in_dir(current.parent):
                return sibling_repo

    return Path.cwd()


def _find_tasks_dir(repo_root: Path) -> Path:
    if "BAND_TASKS_DIR" in os.environ:
        p = Path(os.environ["BAND_TASKS_DIR"]).resolve()
        if p.exists():
            return p

    cur = Path.cwd()
    if (cur / ".agents" / "tasks").exists():
        return cur / ".agents" / "tasks"
    if (cur / "tasks").exists():
        return cur / "tasks"

    if (repo_root / ".agents" / "tasks").exists():
        return repo_root / ".agents" / "tasks"
    if (repo_root / "tasks").exists():
        return repo_root / "tasks"

    return cur / ".agents" / "tasks"

REPO_ROOT = _find_repo_root()
TASKS_DIR = _find_tasks_dir(REPO_ROOT)
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT = 120

import os
import subprocess
from pathlib import Path

def _find_repo_root() -> Path:
    if "BAND_REPO_ROOT" in os.environ:
        p = Path(os.environ["BAND_REPO_ROOT"]).resolve()
        if p.exists():
            return p

    # 1. Try git top level from current working directory
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=True
        )
        top = res.stdout.strip()
        if top and Path(top).exists():
            return Path(top)
    except Exception:
        pass

    # 2. Walk up parent directories to find git root, .agents, or sibling source directory
    cur = Path.cwd()
    for base in [cur, Path(__file__).resolve().parent]:
        for candidate in [base] + list(base.parents):
            # Direct git root
            if (candidate / ".git").exists():
                return candidate

            # Multi-repo layout: check sibling/parent 'source/' directory
            source_dir = candidate / "source" if candidate.name != "source" else candidate
            if source_dir.exists() and source_dir.is_dir():
                for child in sorted(source_dir.iterdir()):
                    if child.is_dir() and ((child / ".git").exists() or (child / "Makefile").exists() or (child / "package.json").exists()):
                        return child

            # Workspace root containing .agents
            if (candidate / ".agents").exists() or (candidate / "pipelines").exists():
                return candidate

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

import os
import subprocess
from pathlib import Path

def _find_repo_root() -> Path:
    if "BAND_REPO_ROOT" in os.environ:
        p = Path(os.environ["BAND_REPO_ROOT"]).resolve()
        if p.exists():
            return p

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

    # Check parent/sibling source directories (e.g. multi-repo layout where agent/ is sibling to source/<repo>)
    cur = Path(__file__).resolve().parent
    for base in [Path.cwd(), cur]:
        for parent in [base] + list(base.parents):
            source_dir = parent.parent / "source" if parent.name == "agent" else parent / "source"
            if source_dir.exists() and source_dir.is_dir():
                for child in source_dir.iterdir():
                    if child.is_dir() and ((child / "Makefile").exists() or (child / ".git").exists()):
                        if child.name == parent.parent.name or child.name == "vidya":
                            return child
                for child in source_dir.iterdir():
                    if child.is_dir() and (child / "Makefile").exists():
                        return child

    for parent in [cur] + list(cur.parents):
        if (parent / ".git").exists() or (parent / ".agents").exists() or (parent / "pipelines").exists():
            return parent

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

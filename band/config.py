import os
import subprocess
from pathlib import Path

def _find_repo_root() -> Path:
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

    cur = Path(__file__).resolve().parent
    for parent in [cur] + list(cur.parents):
        if (parent / ".git").exists() or (parent / ".agents").exists() or (parent / "pipelines").exists():
            return parent

    return Path.cwd()

REPO_ROOT = _find_repo_root()
TASKS_DIR = REPO_ROOT / ".agents" / "tasks" if (REPO_ROOT / ".agents" / "tasks").exists() else REPO_ROOT / "tasks"
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT = 120

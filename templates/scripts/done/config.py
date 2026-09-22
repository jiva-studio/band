import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TASKS_DIR = REPO_ROOT / ".agents" / "tasks"
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT = 120

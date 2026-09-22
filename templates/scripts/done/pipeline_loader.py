from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from done.config import REPO_ROOT
from done.yaml_loader import load_yaml

PIPELINES_DIR = REPO_ROOT / ".agents" / "pipelines"
DEFAULT_PIPELINE_FILE = REPO_ROOT / ".agents" / "pipeline.yaml"

# Standard built-in default pipeline fallback
BUILTIN_PIPELINES = {
    "hardened": {
        "name": "hardened",
        "description": "Full TDD + Mutation Analysis (Diff) + Adversarial Review Loop + Gatekeeper",
        "stages": ["red-phase", "green-phase", "mutation-analysis", "adversarial-review", "gatekeeper"]
    },
    "standard": {
        "name": "standard",
        "description": "Standard TDD Feature (Red -> Green -> Gatekeeper)",
        "stages": ["red-phase", "green-phase", "gatekeeper"]
    },
    "fast": {
        "name": "fast",
        "description": "Fast Hotfix / UI (Solo Coder -> Gatekeeper)",
        "stages": ["implementation", "gatekeeper"]
    },
    "docs": {
        "name": "docs",
        "description": "Documentation / Configs (Author -> Critic -> Gatekeeper)",
        "stages": ["authoring", "critic", "gatekeeper"]
    }
}

def load_pipeline_config(name: Optional[str] = None) -> Dict[str, Any]:
    """Loads a named pipeline profile from .agents/pipelines/<name>.yaml, .agents/pipeline.yaml, or built-in defaults."""
    # 1. Check .agents/pipelines/<name>.yaml
    if name and PIPELINES_DIR.exists():
        p_file = PIPELINES_DIR / f"{name}.yaml"
        if p_file.exists():
            return load_yaml(p_file)

    # 2. Check .agents/pipeline.yaml
    if DEFAULT_PIPELINE_FILE.exists():
        data = load_yaml(DEFAULT_PIPELINE_FILE)
        if name and "pipelines" in data and name in data["pipelines"]:
            return data["pipelines"][name]
        return data

    # 3. Fall back to built-in profile
    if name and name in BUILTIN_PIPELINES:
        return BUILTIN_PIPELINES[name]

    return BUILTIN_PIPELINES["standard"]

def validate_pipeline_manifest(data: Any) -> Tuple[bool, List[str]]:
    """Validates a pipeline.yaml structure."""
    errors = []
    if not isinstance(data, dict):
        return False, ["Pipeline manifest must be a dictionary"]

    # Either carries "stages" or "pipelines"
    if "stages" not in data and "pipelines" not in data:
        errors.append("Pipeline manifest must declare 'stages' list or 'pipelines' mapping")

    if "stages" in data:
        stages = data["stages"]
        if not isinstance(stages, list) or len(stages) == 0:
            errors.append("'stages' must be a non-empty list of stage definitions")
        else:
            stage_ids = set()
            for idx, stage in enumerate(stages):
                if isinstance(stage, dict):
                    sid = stage.get("id")
                    if not sid or not isinstance(sid, str):
                        errors.append(f"Stage #{idx + 1} is missing string 'id'")
                    elif sid in stage_ids:
                        errors.append(f"Duplicate stage id: '{sid}'")
                    else:
                        stage_ids.add(sid)
                elif not isinstance(stage, str):
                    errors.append(f"Stage #{idx + 1} must be a dictionary or stage identifier string")

    return (len(errors) == 0), errors

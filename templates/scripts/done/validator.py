from typing import Any, Dict, List, Tuple
from done.ports.claim_tool import ClaimTool
from done.adapters import (
    MakeClaimTool,
    MutationClaimTool,
    HttpClaimTool,
    CriticClaimTool,
    HygieneClaimTool,
)
from done.pipeline_loader import BUILTIN_PIPELINES, PIPELINES_DIR, DEFAULT_PIPELINE_FILE

TOOL_REGISTRY: Dict[str, ClaimTool] = {
    "make": MakeClaimTool(),
    "mutation": MutationClaimTool(),
    "http": HttpClaimTool(),
    "critic": CriticClaimTool(),
    "hygiene": HygieneClaimTool(),
}

def validate_done_manifest(data: Any) -> Tuple[bool, List[str]]:
    errors = []
    if not isinstance(data, dict):
        return False, ["done.yaml root must be a dictionary/mapping"]

    if "slug" not in data or not isinstance(data["slug"], str) or not data["slug"].strip():
        errors.append("Missing or empty required field: \"slug\"")

    # Validate pipeline reference if present
    pipeline_name = data.get("pipeline")
    if pipeline_name:
        if not isinstance(pipeline_name, str):
            errors.append("\"pipeline\" must be a string identifier (e.g. \"hardened\", \"standard\", \"fast\")")
        else:
            custom_exists = (PIPELINES_DIR / f"{pipeline_name}.yaml").exists()
            if not custom_exists and DEFAULT_PIPELINE_FILE.exists():
                try:
                    from done.yaml_loader import load_yaml
                    p_data = load_yaml(DEFAULT_PIPELINE_FILE)
                    if isinstance(p_data, dict) and "pipelines" in p_data and pipeline_name in p_data["pipelines"]:
                        custom_exists = True
                except Exception:
                    pass
            builtin_exists = pipeline_name in BUILTIN_PIPELINES
            if not custom_exists and not builtin_exists:
                errors.append(f"Unknown pipeline profile: \"{pipeline_name}\"")

    claims = data.get("claims")
    if not claims or not isinstance(claims, list) or len(claims) == 0:
        errors.append("\"claims\" must be a non-empty list of claim definitions")
        return False, errors

    claim_ids = set()
    for idx, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"Claim #{idx + 1} must be a dictionary")
            continue

        cid = claim.get("id")
        if not cid or not isinstance(cid, str):
            errors.append(f"Claim #{idx + 1} is missing a string \"id\"")
        elif cid in claim_ids:
            errors.append(f"Duplicate claim id: \"{cid}\"")
        else:
            claim_ids.add(cid)

        # Support both 'tool' and 'kind'
        kind = claim.get("tool") or claim.get("kind")
        if not kind or not isinstance(kind, str):
            errors.append(f"Claim \"{cid or idx}\" is missing \"tool\" or \"kind\"")
            continue

        tool = TOOL_REGISTRY.get(kind)
        if not tool:
            supported = ", ".join(TOOL_REGISTRY.keys())
            errors.append(f"Claim \"{cid}\" references unknown tool \"{kind}\". Supported tools: {supported}")
            continue

        tool_errors = tool.validate(claim)
        for te in tool_errors:
            errors.append(f"Claim \"{cid}\" ({kind}): {te}")

    return (len(errors) == 0), errors

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from band.ports.claim_tool import ClaimTool
from band.adapters import (
    MakeClaimTool,
    MutationClaimTool,
    HttpClaimTool,
    CriticClaimTool,
    HygieneClaimTool,
)
from band.pipeline_loader import BUILTIN_PIPELINES, PIPELINES_DIR, DEFAULT_PIPELINE_FILE

TOOL_REGISTRY: Dict[str, ClaimTool] = {
    "make": MakeClaimTool(),
    "mutation": MutationClaimTool(),
    "http": HttpClaimTool(),
    "critic": CriticClaimTool(),
    "hygiene": HygieneClaimTool(),
}


def validate_intent_file(file_path: Path) -> Tuple[bool, List[str]]:
    """Validates an intent.md specification against anti-pollution and structural rules."""
    errors = []
    if not file_path.exists():
        return False, [f"Intent file not found: {file_path}"]

    content = file_path.read_text(encoding="utf-8")
    if not content.strip():
        return False, ["Intent file is empty"]

    # 1. Check required structural sections
    required_sections = [
        ("Problem & JTBD", r"(?i)##\s*.*\b(problem|jtbd|why)\b"),
        ("Scope & Non-Goals", r"(?i)##\s*.*\b(scope|non-goals?|boundaries)\b"),
        ("Adversarial Failure Modes", r"(?i)##\s*.*\b(adversarial|failure modes?|mitigations?)\b"),
        ("Invariants & Business Constraints", r"(?i)##\s*.*\b(invariants?|constraints?)\b"),
    ]

    for sec_name, pattern in required_sections:
        if not re.search(pattern, content):
            errors.append(f"Missing required section in intent.md: '{sec_name}'")

    # 2. Check for technical pollution (anti-patterns in pure intent specs)
    tech_patterns = [
        (r"\b(DTO|interface\s+\w+|class\s+\w+|migration\s+\d+)\b", "Code symbols (DTO/interface/class/migration)"),
        (r"\b(GET|POST|PATCH|DELETE)\s+/[a-zA-Z0-9_/]+", "Raw HTTP endpoint routes"),
        (r"\b\w+\.(vue|ts|tsx|py|go|sql|prisma|css|scss)\b", "Source file paths/extensions"),
    ]

    for pattern, label in tech_patterns:
        matches = re.findall(pattern, content)
        if matches:
            errors.append(f"Technical pollution detected in intent.md ({label}): {', '.join(set(matches[:3]))}. Move all technical design to spec.md.")

    return (len(errors) == 0), errors


def validate_done_manifest(data: Any) -> Tuple[bool, List[str]]:
    errors = []
    if not isinstance(data, dict):
        return False, ["Manifest root must be a dictionary/mapping"]

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
                    from band.yaml_loader import load_yaml
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

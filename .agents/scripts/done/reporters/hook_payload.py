import json
from typing import Any, Dict, List

def format_hook_response(
    passed: bool,
    circuit_tripped: bool,
    circuit_reason: str,
    results: List[Dict[str, Any]],
    attempt: int
) -> str:
    if passed:
        return json.dumps({"decision": "allow"})

    if circuit_tripped:
        return json.dumps({
            "decision": "allow",
            "reason": f"Circuit breaker opened: {circuit_reason}. Handing off to human review (NEEDS_HUMAN)."
        })

    # Build clear, actionable continue message
    failed = [r for r in results if not r["passed"]]
    lines = [f"Deterministic checks failed (Attempt {attempt}):"]
    for f in failed:
        cid = f.get("claim_id", f.get("id", "unknown"))
        kind = f.get("kind", f.get("tool", "unknown"))
        msg = f.get("message", "")
        lines.append(f"\n[FAIL] Claim {cid} ({kind}):")
        lines.append(f"  {msg}")

    lines.append("\nYou MUST fix the failing claims above before finishing the task.")
    return json.dumps({
        "decision": "continue",
        "reason": "\n".join(lines)
    })

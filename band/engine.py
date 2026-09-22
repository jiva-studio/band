import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from band.yaml_loader import load_yaml
from band.validator import TOOL_REGISTRY, validate_done_manifest
from band.circuit_breaker import CircuitBreaker
from band.cache import ClaimCache
from band.reporters.markdown_report import write_markdown_report
from band.reporters.hook_payload import format_hook_response

class DoneEngine:
    def __init__(self, spec_path: Path):
        self.spec_path = spec_path
        self.task_dir = spec_path.parent
        self.cache = ClaimCache(self.task_dir)

    def run(self, is_hook_mode: bool = False) -> Dict[str, Any]:
        start_time = time.time()
        if not self.spec_path.exists():
            return {
                "passed": False,
                "error": f"band.yaml not found at {self.spec_path}",
                "results": [],
                "hook_payload": json.dumps({"decision": "allow"}) if is_hook_mode else ""
            }

        try:
            with open(self.spec_path, "r", encoding="utf-8") as f:
                data = load_yaml(self.spec_path)
        except Exception as e:
            return {
                "passed": False,
                "error": f"Failed to parse YAML: {str(e)}",
                "results": [],
                "hook_payload": json.dumps({"decision": "continue", "reason": "Invalid band.yaml syntax"}) if is_hook_mode else ""
            }

        is_valid, errors = validate_done_manifest(data)
        if not is_valid:
            err_msg = "band.yaml schema validation failed:\n" + "\n".join([f"- {e}" for e in errors])
            return {
                "passed": False,
                "error": err_msg,
                "results": [],
                "hook_payload": json.dumps({"decision": "continue", "reason": err_msg}) if is_hook_mode else ""
            }

        slug = data.get("slug", "task")
        claims = data.get("claims", [])
        context = {
            "task_dir": self.task_dir,
            "slug": slug,
            "spec_data": data,
        }

        results = []
        all_passed = True

        for claim in claims:
            kind = claim.get("tool") or claim.get("kind")
            tool = TOOL_REGISTRY[kind]
            claim_id = claim.get("id", "check")

            # 1. Check Content-Addressed Cache
            cached = self.cache.get_cached_result(claim)
            if cached:
                res_dict = {
                    "claim_id": claim_id,
                    "kind": kind,
                    "passed": True,
                    "message": "CACHED (verified on matching diff)",
                    "details": cached.get("details", {}),
                    "duration_ms": 0.0,
                    "cached": True
                }
                results.append(res_dict)
                continue

            # 2. Execute tool
            claim_res = tool.execute(claim, context)
            res_dict = {
                "claim_id": claim_res.claim_id,
                "kind": claim_res.kind,
                "passed": claim_res.passed,
                "message": claim_res.message,
                "details": claim_res.details,
                "duration_ms": claim_res.duration_ms,
                "cached": False
            }
            results.append(res_dict)

            if claim_res.passed:
                self.cache.store_result(claim, passed=True, message=claim_res.message, details=claim_res.details)
            else:
                all_passed = False

        total_duration_ms = (time.time() - start_time) * 1000

        # Markdown report
        write_markdown_report(self.task_dir, slug, all_passed, results, total_duration_ms)

        # Circuit breaker
        cb = CircuitBreaker(self.task_dir)
        failed_claims = [r for r in results if not r["passed"]]
        cb_res = cb.check_and_update(failed_claims)

        hook_payload = format_hook_response(
            passed=all_passed,
            circuit_tripped=cb_res["is_tripped"],
            circuit_reason=cb_res["reason"],
            results=results,
            attempt=cb_res["attempt"]
        )

        return {
            "passed": all_passed,
            "slug": slug,
            "results": results,
            "circuit_breaker": cb_res,
            "hook_payload": hook_payload,
            "total_duration_ms": total_duration_ms,
        }

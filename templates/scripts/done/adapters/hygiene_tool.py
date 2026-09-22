import re
import subprocess
import time
from typing import Any, Dict, List
from done.ports.claim_tool import ClaimTool, ClaimResult
from done.config import REPO_ROOT

class HygieneClaimTool(ClaimTool):
    @property
    def kind(self) -> str:
        return "hygiene"

    def validate(self, claim: Dict[str, Any]) -> List[str]:
        return []

    def execute(self, claim: Dict[str, Any], context: Dict[str, Any]) -> ClaimResult:
        start_time = time.time()
        claim_id = claim.get("id", "diff-hygiene")
        check_stubs = claim.get("no_stubs", True)
        check_skips = claim.get("no_skipped_tests", True)

        try:
            res = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10
            )
            diff = res.stdout
            findings = []

            for line in diff.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    added = line[1:].strip()
                    if check_stubs:
                        if re.search(r"\b(TODO|FIXME)\b", added, re.I):
                            findings.append(f"Forbidden stub in added code: \"{added[:80]}\"")
                        if "throw new Error(\"Not implemented\")" in added:
                            findings.append(f"Unimplemented stub: \"{added[:80]}\"")
                    if check_skips:
                        if re.search(r"\b(it|test|describe)\.skip\b", added) or re.search(r"\b(xit|xdescribe)\b", added):
                            findings.append(f"Forbidden test skip in added code: \"{added[:80]}\"")

            duration_ms = (time.time() - start_time) * 1000
            passed = (len(findings) == 0)
            msg = "\n".join(findings) if not passed else ""

            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=passed,
                message=msg,
                details={"findings": findings},
                duration_ms=duration_ms
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=False,
                message=str(e),
                duration_ms=duration_ms
            )

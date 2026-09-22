import subprocess
import time
from typing import Any, Dict, List
from band.ports.claim_tool import ClaimTool, ClaimResult
from band.config import REPO_ROOT

class MakeClaimTool(ClaimTool):
    @property
    def kind(self) -> str:
        return "make"

    def validate(self, claim: Dict[str, Any]) -> List[str]:
        errors = []
        if "target" not in claim or not isinstance(claim["target"], str) or not claim["target"].strip():
            errors.append("make claim requires a non-empty string \"target\"")
        if "params" in claim and not isinstance(claim["params"], dict):
            errors.append("make claim \"params\" must be a dictionary of key-value pairs")
        return errors

    def execute(self, claim: Dict[str, Any], context: Dict[str, Any]) -> ClaimResult:
        start_time = time.time()
        claim_id = claim.get("id", "make-check")
        target = claim["target"]
        params = claim.get("params", {})
        timeout = claim.get("timeout", 300)

        cmd = ["make", target]
        for k, v in params.items():
            cmd.append(f"{k}={v}")

        try:
            res = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False
            )
            expected_code = claim.get("expect_exit", 0)
            if claim.get("expect") in ["fail", "red", "failure"]:
                passed = (res.returncode != 0)
            else:
                passed = (res.returncode == expected_code)

            duration_ms = (time.time() - start_time) * 1000
            msg = "" if passed else (res.stderr.strip() or res.stdout.strip() or f"make exited with code {res.returncode} (expected {expected_code})")
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=passed,
                message=msg,
                details={"cmd": " ".join(cmd), "returncode": res.returncode, "stdout": res.stdout[-2000:] if not passed else ""},
                duration_ms=duration_ms
            )
        except subprocess.TimeoutExpired:
            duration_ms = (time.time() - start_time) * 1000
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=False,
                message=f"Command timed out after {timeout}s",
                details={"cmd": " ".join(cmd)},
                duration_ms=duration_ms
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=False,
                message=str(e),
                details={"cmd": " ".join(cmd)},
                duration_ms=duration_ms
            )

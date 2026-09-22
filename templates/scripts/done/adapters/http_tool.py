import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Union
from done.ports.claim_tool import ClaimTool, ClaimResult

class HttpClaimTool(ClaimTool):
    @property
    def kind(self) -> str:
        return "http"

    def validate(self, claim: Dict[str, Any]) -> List[str]:
        errors = []
        if "url" not in claim and "path" not in claim:
            errors.append("http claim requires \"url\" or \"path\"")
        if "port" in claim and not isinstance(claim["port"], int):
            errors.append("http claim \"port\" must be an integer (e.g. 3000)")
        if "expect_status" in claim and not isinstance(claim["expect_status"], (int, list)):
            errors.append("http claim \"expect_status\" must be an integer or list of integers")
        return errors

    def execute(self, claim: Dict[str, Any], context: Dict[str, Any]) -> ClaimResult:
        start_time = time.time()
        claim_id = claim.get("id", "http-probe")

        # 1. Resolve target URL (url OR scheme + host + port + path OR base_url + path)
        url = claim.get("url")
        if not url:
            scheme = claim.get("scheme", "http")
            host = claim.get("host", "127.0.0.1")
            port = claim.get("port", 3000)
            base_url = claim.get("base_url")

            if base_url:
                base = base_url.rstrip("/")
            else:
                base = f"{scheme}://{host}:{port}"

            path = claim.get("path", "/")
            url = f"{base}/{path.lstrip('/')}"

        expect_status = claim.get("expect_status", 200)
        expected_statuses = [expect_status] if isinstance(expect_status, int) else expect_status
        expect_body = claim.get("expect_body_contains")
        method = claim.get("method", "GET").upper()
        headers = claim.get("headers", {})
        timeout = claim.get("timeout", 10)

        data = None
        if "json_body" in claim:
            data = json.dumps(claim["json_body"]).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif "body" in claim:
            data = str(claim["body"]).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                body_text = resp.read().decode("utf-8", errors="replace")
                passed = (status in expected_statuses)
                msg = ""

                if not passed:
                    msg = f"Expected status {expected_statuses}, got {status}"
                elif expect_body and expect_body not in body_text:
                    passed = False
                    msg = f"Response body did not contain expected substring: \"{expect_body}\""

                duration_ms = (time.time() - start_time) * 1000
                return ClaimResult(
                    claim_id=claim_id,
                    kind=self.kind,
                    passed=passed,
                    message=msg,
                    details={"url": url, "status": status, "body_snippet": body_text[:200]},
                    duration_ms=duration_ms
                )
        except urllib.error.HTTPError as e:
            duration_ms = (time.time() - start_time) * 1000
            body_text = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            passed = (e.code in expected_statuses)
            msg = ""

            if not passed:
                msg = f"Expected status {expected_statuses}, got {e.code}"
            elif expect_body and expect_body not in body_text:
                passed = False
                msg = f"Response body did not contain expected substring: \"{expect_body}\""

            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=passed,
                message=msg,
                details={"url": url, "status": e.code, "body_snippet": body_text[:200]},
                duration_ms=duration_ms
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=False,
                message=f"HTTP probe failed to reach {url}: {str(e)}",
                details={"url": url},
                duration_ms=duration_ms
            )

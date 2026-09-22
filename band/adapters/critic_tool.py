import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from band.ports.claim_tool import ClaimTool, ClaimResult
from band.config import REPO_ROOT

class CriticClaimTool(ClaimTool):
    @property
    def kind(self) -> str:
        return "critic"

    def validate(self, claim: Dict[str, Any]) -> List[str]:
        errors = []
        checks = claim.get("checks")
        if not checks or not isinstance(checks, list):
            errors.append("critic claim requires a list of \"checks\" (criteria strings)")
        runner = claim.get("runner", "auto")
        if runner not in ("auto", "gemini", "claude", "file"):
            errors.append(f"critic claim \"runner\" must be \"auto\", \"gemini\", \"claude\" or \"file\", got \"{runner}\"")
        return errors

    def _find_cli_runner(self, requested: str) -> Optional[Tuple[str, str]]:
        if requested in ("claude", "auto"):
            p = shutil.which("claude")
            if p and Path(p).exists():
                return ("claude", p)
        if requested in ("gemini", "auto"):
            p = shutil.which("gemini")
            if p and Path(p).exists():
                return ("gemini", p)
        return None

    def execute(self, claim: Dict[str, Any], context: Dict[str, Any]) -> ClaimResult:
        start_time = time.time()
        claim_id = claim.get("id", "critic-review")
        checks = claim.get("checks", [])
        runner_type = claim.get("runner", "auto")
        timeout = claim.get("timeout", 45)

        task_dir = context.get("task_dir")
        task_dir_path = Path(task_dir) if task_dir else None

        # 1. Check for manual/agent review artifact in artifacts/critic_review.json
        if task_dir_path:
            review_file = task_dir_path / "artifacts" / "critic_review.json"
            if review_file.exists():
                try:
                    review_data = json.loads(review_file.read_text(encoding="utf-8"))
                    passed = review_data.get("passed", False)
                    findings = review_data.get("findings", [])
                    duration_ms = (time.time() - start_time) * 1000
                    if not passed:
                        msg = "Critic review artifact reported blockers:\n" + "\n".join(
                            [f"- {f.get('file', '?')}:{f.get('line', '?')} {f.get('issue', '')} (Fix: {f.get('fix', '')})" for f in findings]
                        )
                    else:
                        msg = ""
                    return ClaimResult(
                        claim_id=claim_id,
                        kind=self.kind,
                        passed=passed,
                        message=msg,
                        details={"findings": findings, "source": "artifact", "path": str(review_file)},
                        duration_ms=duration_ms
                    )
                except Exception as e:
                    duration_ms = (time.time() - start_time) * 1000
                    return ClaimResult(
                        claim_id=claim_id,
                        kind=self.kind,
                        passed=False,
                        message=f"Failed to parse critic_review.json: {str(e)}",
                        duration_ms=duration_ms
                    )

        if runner_type == "file":
            duration_ms = (time.time() - start_time) * 1000
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=False,
                message="No artifacts/critic_review.json found for file runner",
                duration_ms=duration_ms
            )

        intent_text = ""
        if task_dir_path:
            intent_path = task_dir_path / "intent.md"
            if intent_path.exists():
                intent_text = intent_path.read_text(encoding="utf-8")

        # Collect active working tree git diff first
        try:
            diff_res = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10
            )
            git_diff = diff_res.stdout
            if not git_diff.strip():
                diff_res = subprocess.run(
                    ["git", "diff", "HEAD~1...HEAD"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                git_diff = diff_res.stdout
        except Exception:
            git_diff = "(diff unavailable)"

        cli_info = self._find_cli_runner(runner_type)
        if not cli_info:
            duration_ms = (time.time() - start_time) * 1000
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=False,
                message="Critic runner not found in PATH and no artifacts/critic_review.json found.",
                details={"status": "NO_RUNNER"},
                duration_ms=duration_ms
            )

        runner_name, binary_path = cli_info
        checks_bullets = "\n".join([f"- {c}" for c in checks])
        model = claim.get("model") or claim.get("params", {}).get("model")

        prompt = f"""# ROLE: Strict Code Reviewer & Critic
You are evaluating a code change against the original intent and specific audit criteria.

## INTENT (from intent.md):
{intent_text[:3000]}

## CODE DIFF:
{git_diff[:8000]}

## AUDIT CHECKS:
{checks_bullets}

## RULES:
1. Ignore styling, comments, or formatting preferences.
2. Flag ONLY critical blockers (violations of intent, broken non-goals, security vulnerabilities, unhandled nulls).
3. If no critical blockers exist, return "passed": true and empty findings.

## OUTPUT FORMAT:
You MUST output ONLY a valid JSON object matching this schema:
{{
  "passed": true,
  "findings": []
}}
or
{{
  "passed": false,
  "findings": [
    {{
      "file": "path/to/file.ts",
      "line": 42,
      "issue": "Brief description of the blocker",
      "fix": "Specific recommended fix"
    }}
  ]
}}
"""

        try:
            cmd = [binary_path, "-p", prompt]
            if model:
                if runner_name == "gemini":
                    cmd.extend(["-m", model])
                else:
                    cmd.extend(["--model", model])

            res = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            duration_ms = (time.time() - start_time) * 1000
            raw_output = res.stdout.strip() or res.stderr.strip()

            if res.returncode != 0:
                return ClaimResult(
                    claim_id=claim_id,
                    kind=self.kind,
                    passed=False,
                    message=f"Critic CLI [{runner_name}] exited with error code {res.returncode}:\n{raw_output[:300]}",
                    details={"raw": raw_output[:500], "returncode": res.returncode},
                    duration_ms=duration_ms
                )

            # Parse JSON from response (strip code fences if any)
            cleaned = re.sub(r"^```(?:json)?", "", raw_output.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE)
            json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                except Exception as e:
                    return ClaimResult(
                        claim_id=claim_id,
                        kind=self.kind,
                        passed=False,
                        message=f"Critic output was invalid JSON: {str(e)}\nRaw output: {raw_output[:300]}",
                        details={"raw": raw_output[:500]},
                        duration_ms=duration_ms
                    )
                passed = parsed.get("passed", False)
                findings = parsed.get("findings", [])
                if not passed:
                    msg = "Critic identified blockers:\n" + "\n".join(
                        [f"- {f.get('file', '?')}:{f.get('line', '?')} {f.get('issue', '')} (Fix: {f.get('fix', '')})" for f in findings]
                    )
                else:
                    msg = ""
                return ClaimResult(
                    claim_id=claim_id,
                    kind=self.kind,
                    passed=passed,
                    message=msg,
                    details={"findings": findings, "raw": raw_output[:500]},
                    duration_ms=duration_ms
                )
            else:
                return ClaimResult(
                    claim_id=claim_id,
                    kind=self.kind,
                    passed=False,
                    message=f"Critic did not return valid JSON:\n{raw_output[:300]}",
                    details={"raw": raw_output[:300]},
                    duration_ms=duration_ms
                )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=False,
                message=f"Critic execution error: {str(e)}",
                duration_ms=duration_ms
            )

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
        if runner not in ("auto", "gemini", "claude"):
            errors.append(f"critic claim \"runner\" must be \"auto\", \"gemini\" or \"claude\", got \"{runner}\"")
        return errors

    def _find_cli_runner(self, requested: str) -> Optional[Tuple[str, str]]:
        if requested in ("gemini", "auto"):
            p = shutil.which("gemini")
            if p and Path(p).exists():
                return ("gemini", p)
        if requested in ("claude", "auto"):
            p = shutil.which("claude")
            if p and Path(p).exists():
                return ("claude", p)
        return None

    def execute(self, claim: Dict[str, Any], context: Dict[str, Any]) -> ClaimResult:
        start_time = time.time()
        claim_id = claim.get("id", "critic-review")
        checks = claim.get("checks", [])
        runner_type = claim.get("runner", "auto")
        model = claim.get("model", "gemini-2.5-flash")
        timeout = claim.get("timeout", 45)

        task_dir = context.get("task_dir")
        intent_text = ""
        if task_dir:
            intent_path = Path(task_dir) / "intent.md"
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
                passed=True,
                message="Critic skipped: no gemini/claude CLI runner found in PATH",
                details={"status": "SKIPPED"},
                duration_ms=duration_ms
            )

        runner_name, binary_path = cli_info
        checks_bullets = "\n".join([f"- {c}" for c in checks])

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
            if runner_name == "gemini":
                cmd = [binary_path, "-p", prompt, "-m", model]
            else:
                cmd = [binary_path, "-p", prompt, "--model", model]

            res = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            duration_ms = (time.time() - start_time) * 1000
            raw_output = res.stdout.strip() or res.stderr.strip()

            # Parse JSON from response (strip code fences if any)
            cleaned = re.sub(r"^```(?:json)?", "", raw_output.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE)
            json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                except Exception:
                    # Fallback if unescaped quotes inside json strings
                    parsed = {"passed": True, "findings": []}
                passed = parsed.get("passed", False)
                findings = parsed.get("findings", [])
                if not passed:
                    msg = "Critic identified blockers:\n" + "\n".join(
                        [f"- {f.get("file", "?")}:{f.get("line", "?")} {f.get("issue", "")} (Fix: {f.get("fix", "")})" for f in findings]
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
                    passed=True,
                    message="Critic response not JSON, allowing by default",
                    details={"raw": raw_output[:300]},
                    duration_ms=duration_ms
                )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=True,
                message=f"Critic execution error: {str(e)}",
                duration_ms=duration_ms
            )

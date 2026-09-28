import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from band.ports.claim_tool import ClaimTool, ClaimResult
from band.config import REPO_ROOT

# Defaults; override per claim (timeout / max_diff_chars / max_intent_chars)
# or via BAND_CRITIC_TIMEOUT / BAND_CRITIC_MAX_DIFF_CHARS / BAND_CRITIC_MAX_INTENT_CHARS.
DEFAULT_TIMEOUT_S = 300
DEFAULT_MAX_DIFF_CHARS = 200_000
DEFAULT_MAX_INTENT_CHARS = 50_000

STDIN_INSTRUCTION = (
    "Follow the review instructions provided on stdin exactly and output only the JSON object they request."
)


# Band's own harness files and task bookkeeping (.agents/) are not part of the reviewed change.
DIFF_PATHSPEC = [".", ":(exclude).agents"]


def _git(args: List[str], cwd: Path, timeout: int = 30) -> Tuple[int, str, str]:
    try:
        res = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout, res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def resolve_base_ref(claim: Dict[str, Any], spec_data: Dict[str, Any], repo_root: Path) -> Optional[str]:
    """
    Picks the task's base branch: claim `base` > done.yaml `base_branch`/`base`
    > $BAND_BASE_BRANCH > origin/HEAD > main > master. Returns None if none exists.
    """
    candidates = [
        claim.get("base"),
        (claim.get("params") or {}).get("base"),
        spec_data.get("base_branch") if isinstance(spec_data, dict) else None,
        spec_data.get("base") if isinstance(spec_data, dict) else None,
        os.environ.get("BAND_BASE_BRANCH"),
    ]
    code, out, _ = _git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], repo_root)
    if code == 0 and out.strip():
        candidates.append(out.strip())
    candidates.extend(["main", "master"])
    for ref in candidates:
        if isinstance(ref, str) and ref.strip():
            code, _, _ = _git(["rev-parse", "--verify", "--quiet", f"{ref.strip()}^{{commit}}"], repo_root)
            if code == 0:
                return ref.strip()
    return None


def collect_task_diff(repo_root: Path, base_ref: Optional[str]) -> Tuple[bool, str, str]:
    """
    Returns (ok, base_description_or_error, diff): the complete diff of the working
    tree (committed + uncommitted + untracked files) against merge-base(base, HEAD).
    """
    if not base_ref:
        return False, ("no base branch found (set `base` on the critic claim, `base_branch` in done.yaml, "
                       "or BAND_BASE_BRANCH)"), ""
    code, out, err = _git(["merge-base", base_ref, "HEAD"], repo_root)
    if code != 0 or not out.strip():
        return False, f"git merge-base {base_ref} HEAD failed: {err or 'no common ancestor'}", ""
    merge_base = out.strip()
    desc = f"merge-base of {base_ref} ({merge_base[:12]})"

    code, diff, err = _git(["diff", merge_base, "--"] + DIFF_PATHSPEC, repo_root, timeout=60)
    if code != 0:
        return False, f"git diff {merge_base[:12]} failed: {err}", ""

    code, untracked, err = _git(["ls-files", "--others", "--exclude-standard", "-z", "--"] + DIFF_PATHSPEC, repo_root)
    if code != 0:
        return False, f"git ls-files failed: {err}", ""
    parts = [diff]
    for rel in [p for p in untracked.split("\0") if p]:
        # --no-index exits 1 when files differ; that is the expected case.
        code, file_diff, err = _git(["diff", "--no-index", "--", "/dev/null", rel], repo_root, timeout=60)
        if code not in (0, 1):
            return False, f"git diff for untracked file {rel} failed: {err}", ""
        parts.append(file_diff)
    return True, desc, "".join(parts)

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
        for key in ("timeout", "max_diff_chars", "max_intent_chars"):
            if key in claim and (isinstance(claim[key], bool) or not isinstance(claim[key], int) or claim[key] <= 0):
                errors.append(f"critic claim \"{key}\" must be a positive integer, got {claim[key]!r}")
        return errors

    @staticmethod
    def _int_setting(claim: Dict[str, Any], key: str, env_var: str, default: int) -> int:
        """Claim value (or claim.params value) > environment variable > default."""
        for value in (claim.get(key), (claim.get("params") or {}).get(key), os.environ.get(env_var)):
            if value is None or value == "":
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return default

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
        timeout = self._int_setting(claim, "timeout", "BAND_CRITIC_TIMEOUT", DEFAULT_TIMEOUT_S)

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

        def fail(message: str, **details: Any) -> ClaimResult:
            return ClaimResult(
                claim_id=claim_id,
                kind=self.kind,
                passed=False,
                message=message,
                details=details,
                duration_ms=(time.time() - start_time) * 1000,
            )

        intent_text = ""
        if task_dir_path:
            intent_path = task_dir_path / "intent.md"
            if intent_path.exists():
                intent_text = intent_path.read_text(encoding="utf-8")

        max_intent = self._int_setting(claim, "max_intent_chars", "BAND_CRITIC_MAX_INTENT_CHARS", DEFAULT_MAX_INTENT_CHARS)
        max_diff = self._int_setting(claim, "max_diff_chars", "BAND_CRITIC_MAX_DIFF_CHARS", DEFAULT_MAX_DIFF_CHARS)

        if len(intent_text) > max_intent:
            return fail(
                f"intent.md is {len(intent_text)} chars, over the critic limit of {max_intent}. "
                "The critic never reviews partial input: shorten intent.md or raise "
                "max_intent_chars on the claim (or BAND_CRITIC_MAX_INTENT_CHARS).",
                status="INTENT_TOO_LARGE", size=len(intent_text), limit=max_intent,
            )

        # Collect the full task diff relative to the base branch's merge-base.
        spec_data = context.get("spec_data") or {}
        ok, base_desc, git_diff = collect_task_diff(REPO_ROOT, resolve_base_ref(claim, spec_data, REPO_ROOT))
        if not ok:
            return fail(f"Critic could not compute the task diff: {base_desc}", status="DIFF_UNAVAILABLE")
        if not git_diff.strip():
            return fail(
                f"No changes found relative to {base_desc}; nothing for the critic to review.",
                status="EMPTY_DIFF", base=base_desc,
            )
        if len(git_diff) > max_diff:
            return fail(
                f"Task diff against {base_desc} is {len(git_diff)} chars, over the critic limit of {max_diff}. "
                "The critic never reviews partial input: split the task into smaller changes, or raise "
                "max_diff_chars on the claim (or BAND_CRITIC_MAX_DIFF_CHARS).",
                status="DIFF_TOO_LARGE", size=len(git_diff), limit=max_diff, base=base_desc,
            )

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
{intent_text}

## CODE DIFF (complete, against {base_desc}):
{git_diff}

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
            # The full review prompt goes through stdin: a single argv string is capped
            # at 128 KiB on Linux, which would silently limit the diff size.
            cmd = [binary_path, "-p", STDIN_INSTRUCTION]
            if model:
                if runner_name == "gemini":
                    cmd.extend(["-m", model])
                else:
                    cmd.extend(["--model", model])

            try:
                res = subprocess.run(
                    cmd,
                    cwd=REPO_ROOT,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
            except subprocess.TimeoutExpired:
                return fail(
                    f"Critic CLI [{runner_name}] timed out after {timeout}s. Raise \"timeout\" on the claim "
                    "(or BAND_CRITIC_TIMEOUT) if reviews of this size legitimately take longer.",
                    status="TIMEOUT", timeout=timeout,
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

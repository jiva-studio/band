import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from band.config import REPO_ROOT

class ClaimCache:
    """Content-Addressed Cache for Verification Claims."""

    def __init__(self, task_dir: Optional[Path]):
        self.task_dir = task_dir
        self.state_file = (task_dir / "artifacts" / "state.json") if task_dir else None

    def _read_state(self) -> Dict[str, Any]:
        if not self.state_file or not self.state_file.exists():
            return {"claims": {}}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {"claims": {}}

    def _write_state(self, state: Dict[str, Any]) -> None:
        if not self.state_file:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def compute_fingerprint(self, claim: Dict[str, Any]) -> str:
        """Computes SHA256 composite fingerprint over claim definition and target git diff."""
        claim_id = claim.get("id", "")
        kind = claim.get("tool") or claim.get("kind", "")
        params = json.dumps(claim.get("params", {}), sort_keys=True)
        target = claim.get("target") or claim.get("package") or claim.get("params", {}).get("PKG", "")

        # Get git diff for the workspace or target path if it is an actual filesystem path
        diff_str = ""
        try:
            cmd = ["git", "-C", str(REPO_ROOT), "diff", "HEAD"]
            if target and isinstance(target, str) and (REPO_ROOT / target).exists():
                cmd.extend(["--", target])
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            diff_str = res.stdout
        except Exception:
            diff_str = "no-git"

        # Also capture untracked files list and content hashes
        untracked_data = []
        try:
            status_res = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in status_res.stdout.splitlines():
                if line.startswith("?? "):
                    fpath = line[3:].strip().strip('"')
                    full_p = REPO_ROOT / fpath
                    if full_p.is_file():
                        try:
                            untracked_data.append(f"{fpath}:{hashlib.md5(full_p.read_bytes()).hexdigest()}")
                        except Exception:
                            untracked_data.append(fpath)
                    else:
                        untracked_data.append(fpath)
                else:
                    untracked_data.append(line)
        except Exception:
            untracked_data = []

        raw = f"{claim_id}|{kind}|{params}|{diff_str}|{'|'.join(untracked_data)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_cached_result(self, claim: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Returns cached receipt if fingerprint matches and status is passed."""
        claim_id = claim.get("id")
        if not claim_id:
            return None

        state = self._read_state()
        cached = state.get("claims", {}).get(claim_id)
        if not cached:
            return None

        curr_fingerprint = self.compute_fingerprint(claim)
        if cached.get("fingerprint") == curr_fingerprint and cached.get("passed") is True:
            return cached

        return None

    def store_result(self, claim: Dict[str, Any], passed: bool, message: str = "", details: Optional[Dict[str, Any]] = None) -> None:
        """Stores verified claim receipt in state.json."""
        claim_id = claim.get("id")
        if not claim_id:
            return

        state = self._read_state()
        if "claims" not in state:
            state["claims"] = {}

        fingerprint = self.compute_fingerprint(claim)
        state["claims"][claim_id] = {
            "passed": passed,
            "fingerprint": fingerprint,
            "message": message,
            "details": details or {},
        }
        self._write_state(state)

    def get(self, claim_id: str, claim: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convenience alias for get_cached_result."""
        res = self.get_cached_result(claim)
        if res:
            return {"success": res.get("passed", False), "message": res.get("message", ""), "details": res.get("details", {})}
        return None

    def put(self, claim_id: str, claim: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Convenience alias for store_result."""
        self.store_result(
            claim=claim,
            passed=result.get("success", result.get("passed", False)),
            message=result.get("message", ""),
            details=result.get("details", {})
        )

    def clear(self) -> None:
        """Clears cached receipts."""
        self._write_state({"claims": {}})

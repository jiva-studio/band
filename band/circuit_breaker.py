import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from band.config import DEFAULT_MAX_RETRIES

class CircuitBreaker:
    def __init__(self, task_dir: Optional[Path], max_retries: int = DEFAULT_MAX_RETRIES):
        self.task_dir = task_dir
        self.max_retries = max_retries
        self.state_file = (task_dir / "artifacts" / "circuit.json") if task_dir else None

    def _read_state(self) -> Dict[str, Any]:
        if not self.state_file or not self.state_file.exists():
            return {"attempt": 0, "last_error_hash": "", "stagnant_count": 0}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {"attempt": 0, "last_error_hash": "", "stagnant_count": 0}

    def _write_state(self, state: Dict[str, Any]) -> None:
        if not self.state_file:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def check_and_update(self, failed_claims: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Checks if circuit breaker should trip.
        Returns: {"is_tripped": bool, "reason": str, "attempt": int}
        """
        if not failed_claims:
            if self.state_file and self.state_file.exists():
                self.state_file.unlink(missing_ok=True)
            return {"is_tripped": False, "reason": "", "attempt": 0}

        state = self._read_state()
        attempt = state.get("attempt", 0) + 1
        stagnant_count = state.get("stagnant_count", 0)

        # Compute hash of failed claims
        error_fingerprint = "|".join([f"{c.get('claim_id', c.get('id', ''))}:{c.get('message', '')}" for c in failed_claims])
        curr_hash = hashlib.md5(error_fingerprint.encode("utf-8")).hexdigest()

        if curr_hash == state.get("last_error_hash"):
            stagnant_count += 1
        else:
            stagnant_count = 0

        state["attempt"] = attempt
        state["last_error_hash"] = curr_hash
        state["stagnant_count"] = stagnant_count
        self._write_state(state)

        if attempt > self.max_retries:
            return {
                "is_tripped": True,
                "reason": f"Exceeded maximum automated retry budget ({self.max_retries} attempts).",
                "attempt": attempt
            }

        if stagnant_count >= 1:
            return {
                "is_tripped": True,
                "reason": "Stagnation detected: exact same failure signature repeated without progress.",
                "attempt": attempt
            }

        return {"is_tripped": False, "reason": "", "attempt": attempt}

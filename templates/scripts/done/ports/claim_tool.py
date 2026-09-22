from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class ClaimResult:
    claim_id: str
    kind: str
    passed: bool
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

class ClaimTool(ABC):
    @property
    @abstractmethod
    def kind(self) -> str:
        """Unique kind string identifier (e.g. make, mutation, critic)."""
        pass

    @abstractmethod
    def validate(self, claim: Dict[str, Any]) -> List[str]:
        """Validate claim schema and parameters. Returns list of error messages."""
        pass

    @abstractmethod
    def execute(self, claim: Dict[str, Any], context: Dict[str, Any]) -> ClaimResult:
        """Execute the claim check and return a ClaimResult."""
        pass

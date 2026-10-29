"""A single monotonic wall-clock budget, including the synthesis reserve."""
from __future__ import annotations
from dataclasses import dataclass
import time

@dataclass(frozen=True)
class RunBudget:
    end: float
    synthesis_reserve: float = 15.0

    @classmethod
    def start(cls, seconds: float, reserve: float = 15.0) -> "RunBudget":
        if seconds <= 0 or reserve < 0:
            raise ValueError("Invalid request deadline")
        return cls(time.monotonic() + seconds, min(reserve, seconds))

    def remaining(self) -> float:
        return max(0.0, self.end - time.monotonic())

    def debate_remaining(self) -> float:
        return max(0.0, self.remaining() - self.synthesis_reserve)

    def allowed(self, limit: float, *, synthesis: bool = False) -> float:
        return min(limit, self.remaining() if synthesis else self.debate_remaining())

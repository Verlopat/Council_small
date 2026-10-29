"""Role reservations are immutable within a run, including during fallback."""
from __future__ import annotations
from dataclasses import dataclass
from council.families import FAMILIES

class RoleConflict(ValueError):
    pass

@dataclass(frozen=True)
class Assignment:
    solvers: tuple[str, ...]
    translator: str = "glm"
    judge: str = "gemini"
    auditor: str | None = None
    optional_critics: tuple[str, ...] = ()

    def __post_init__(self):
        names = set(self.solvers) | {self.translator, self.judge}
        if self.auditor:
            names.add(self.auditor)
        names.update(self.optional_critics)
        if any(n not in FAMILIES for n in names):
            raise RoleConflict("Unknown model family")
        if len(set(self.solvers)) != len(self.solvers):
            raise RoleConflict("Duplicate solver lineage")
        if self.judge in (set(self.solvers) | {self.translator} | set(self.optional_critics)
                          | ({self.auditor} if self.auditor else set())):
            raise RoleConflict("Synthesis family must remain entirely separate")
        if self.auditor and self.auditor in (set(self.solvers) | {self.translator}):
            raise RoleConflict("Audit family must not review its own prior work")

    def allowed(self, role: str, family: str, *, claim_owner: str | None = None) -> bool:
        if family not in FAMILIES:
            return False
        if role == "judge":
            return family == self.judge
        if family == self.judge:
            return False
        if role in {"translator", "hunter", "critic", "relevance"} and claim_owner == family:
            return False
        if role == "solver":
            return family in self.solvers
        if role == "auditor":
            return family == self.auditor and family != self.judge
        if role == "translator":
            return family == self.translator
        return family != self.judge

    def fallback(self, family: str):
        """Only same-family endpoints; never silently substitute a paid/different lineage."""
        return FAMILIES[family].endpoints

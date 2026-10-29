"""Deterministic coverage, non-evidence concession and stale-dependency flags."""
from __future__ import annotations
from dataclasses import dataclass
from council.models import ClaimLedger, ClaimStatus

@dataclass(frozen=True)
class Flag:
    claim_id: str
    reason: str
    reference: str = ""

def deterministic_flags(ledger: ClaimLedger, requirements: dict[str, list[str]] | None = None) -> list[Flag]:
    flags = []
    for claim in ledger.claims.values():
        if claim.needs_re_evaluation:
            flags.append(Flag(claim.id, "dependency_needs_re_evaluation"))
        if claim.status is ClaimStatus.SUPPORTED and not any(
            ledger.evidence[e].independently_checked for e in claim.evidence_ids
            if e in ledger.evidence):
            flags.append(Flag(claim.id, "unsupported_supported"))
    for requirement, claim_ids in (requirements or {}).items():
        if not claim_ids or not any(cid in ledger.claims for cid in claim_ids):
            flags.append(Flag("", "requirement_uncovered:" + requirement))
    return flags

class ReopenGate:
    def __init__(self):
        self.seen: set[tuple[int, str]] = set()
    def authorize(self, round_number: int, claim_id: str, *, new_evidence: bool) -> bool:
        key = (round_number, claim_id)
        if key in self.seen or not new_evidence:
            return False
        self.seen.add(key)
        return True

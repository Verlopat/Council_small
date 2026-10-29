"""Deterministic evidence checks. A failed proof is NOT a disproved theorem."""
from __future__ import annotations
from dataclasses import dataclass
from council.models import Evidence, EvidenceKind, ClaimLedger
from council.protocol import Act, Message

class EvidenceRejected(ValueError):
    pass

@dataclass(frozen=True)
class PolarityResult:
    acceptable: bool
    changes_claim: bool
    reason: str
    target_status: str | None = None

def evaluate_polarity(msg: Message, ledger: ClaimLedger,
                      *, prior_owner_evidence: set[str] | None = None) -> PolarityResult:
    if msg.thread not in ledger.claims:
        raise EvidenceRejected("Unknown thread/claim")
    claim = ledger.claims[msg.thread]
    referenced: list[Evidence] = []
    for ref in msg.evidence:
        item = ledger.evidence.get(ref)
        if item is None:
            raise EvidenceRejected("Evidence reference does not exist")
        if item.claim_id != msg.thread or item.claim_version != claim.version:
            raise EvidenceRejected("Evidence not scoped to this claim and version")
        referenced.append(item)
    used = prior_owner_evidence or set()
    new = [e for e in referenced if e.id not in used]
    if msg.act is Act.DEFEND:
        if msg.sender_family != claim.owner_family:
            raise EvidenceRejected("Only claim owner may defend")
        if not any(e.independently_checked and e.outcome == "pass" and
                   e.kind in {EvidenceKind.TEST, EvidenceKind.FORMAL_PROOF, EvidenceKind.SOURCE}
                   for e in new):
            return PolarityResult(False, False, "no new scoped passing evidence")
        return PolarityResult(True, True, "bounded support", "supported")
    if msg.act is Act.CONCEDE:
        if msg.sender_family != claim.owner_family:
            raise EvidenceRejected("Only claim owner may concede")
        if not any(e.independently_checked and e.outcome == "fail" for e in new):
            return PolarityResult(False, False, "pressure-only concession")
        # A broken argument may leave a true statement; do NOT mark contradicted.
        if any(e.kind is EvidenceKind.COUNTEREXAMPLE and e.independently_checked
               and e.outcome == "fail" for e in new):
            return PolarityResult(True, True, "validated counterexample", "contradicted")
        return PolarityResult(True, True, "argument conceded, statement unresolved", "unresolved")
    if msg.act is Act.CHALLENGE:
        if msg.sender_family == claim.owner_family:
            raise EvidenceRejected("A challenge must be cross-family")
        genuine = any(e.independently_checked and e.outcome == "fail" for e in new)
        # A step reference permits a challenge but is not independently validated.
        if not genuine and not msg.step_ref:
            return PolarityResult(False, False, "requires a step reference or failing evidence")
        return PolarityResult(True, genuine, "challenge recorded; check its consequence",
                              "contradicted" if any(e.kind is EvidenceKind.COUNTEREXAMPLE and
                                e.independently_checked and e.outcome == "fail" for e in new)
                              else "unresolved")
    if msg.act is Act.WITHDRAW:
        if msg.sender_family != claim.owner_family:
            raise EvidenceRejected("Only claim owner can withdraw")
        return PolarityResult(True, True, "owner withdrew claim", "withdrawn")
    if msg.act is Act.RESULT:
        # Only trusted verifier service may deliver RESULT.
        if msg.sender_family != "verifier":
            raise EvidenceRejected("LLM cannot certify verifier results")
        return PolarityResult(True, False, "verified result must be recorded by verifier")
    return PolarityResult(True, False, "non-decisive act")

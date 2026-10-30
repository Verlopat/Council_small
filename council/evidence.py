"""Deterministic evidence-reference and polarity validation.

A review is never equivalent to an independent failing check.
"""
from __future__ import annotations
from council.protocol import Act, Message
from council.models import Evidence, EvidenceKind, ClaimLedger

def polarity_ok(message: Message, ledger: ClaimLedger, *,
                owner_last_refs: frozenset[str] = frozenset(),
                thread_refs: frozenset[str] = frozenset()) -> bool:
    claim = ledger.claims.get(message.thread)
    if claim is None:
        return False
    refs = [ledger.evidence.get(ref) for ref in message.evidence]
    if any(r is None or r.claim_id != claim.id or r.claim_version != claim.version
           for r in refs):
        return False
    verified = [r for r in refs if r is not None and r.independently_checked]
    if message.act is Act.CONCEDE:
        # A valid failing check contradicts only its stated scope, and a
        # concession to a broken proof does not refute its conclusion.
        return any(r.outcome == "fail" and r.id not in owner_last_refs
                   for r in verified)
    if message.act is Act.DEFEND:
        return any(r.outcome == "pass" and r.id not in thread_refs
                   for r in verified)
    if message.act is Act.CHALLENGE:
        # An actual independently checked failure or a *recorded* counterexample
        # is required. A bare assertion is just an unverified objection.
        return any(r.outcome == "fail" and r.kind in
                   {EvidenceKind.TEST, EvidenceKind.COUNTEREXAMPLE,
                    EvidenceKind.FORMAL_PROOF} for r in verified)
    if message.act in (Act.WITHDRAW, Act.ABSTAIN, Act.REQUEST_EVIDENCE,
                       Act.ASK, Act.ANSWER, Act.PROPOSE):
        return True
    if message.act in (Act.RESULT, Act.VERIFY_REQUEST, Act.REPAIR):
        return bool(message.evidence)
    return False

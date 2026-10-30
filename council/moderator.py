"""Single-writer claim moderator, enforcing evidence-before-status and round gating."""
from __future__ import annotations
from council.models import ClaimLedger, ClaimStatus, Evidence
from council.evidence import evaluate_polarity, EvidenceRejected
from council.protocol import Message, Act
from council.bus import MessageBus, MessageCap
from council.overseer import ReopenGate, deterministic_flags

class Moderator:
    def __init__(self, ledger: ClaimLedger | None = None, bus: MessageBus | None = None,
                 events=None):
        self.ledger = ledger or ClaimLedger()
        self.bus = bus or MessageBus()
        self.events = events or (lambda *_args, **_kwargs: None)
        self.current_round = 0
        self.new_evidence = 0
        self.gate = ReopenGate()
        self.owner_last_refs: dict[str, set[str]] = {}

    def record_result(self, evidence: Evidence) -> None:
        if not evidence.independently_checked:
            raise EvidenceRejected("Verifier results must be independently checked")
        self.ledger.attach(evidence)
        self.new_evidence += 1
        self.events("evidence_recorded", evidence_id=evidence.id,
                    claim_id=evidence.claim_id, claim_version=evidence.claim_version,
                    kind=evidence.kind.value, outcome=evidence.outcome)

    def submit(self, msg: Message) -> str:
        decision = evaluate_polarity(
            msg, self.ledger,
            prior_owner_evidence=self.owner_last_refs.get(msg.thread, set()))
        if not decision.acceptable:
            self.events("conformity_flag", claim_id=msg.thread, reason=decision.reason)
            return "rejected"
        try:
            result = self.bus.deliver(msg)
        except MessageCap:
            cause = self.bus.stalemates().get(msg.thread, "cap_hit")
            self.events("stalemate", claim_id=msg.thread, cause=cause)
            raise
        if result == "duplicate":
            self.events("dedupe_dropped", claim_id=msg.thread, message_id=msg.id)
            if self.bus.stalemates().get(msg.thread) == "dedupe_dropped":
                self.events("stalemate", claim_id=msg.thread, cause="dedupe_dropped")
            return result
        if msg.act is Act.ABSTAIN:
            self.bus.close(msg.thread, "agents_gave_up")
            self.events("stalemate", claim_id=msg.thread, cause="agents_gave_up")
        claim = self.ledger.claims[msg.thread]
        if decision.changes_claim and decision.target_status:
            if decision.target_status == "supported":
                claim.status = ClaimStatus.SUPPORTED
            elif decision.target_status == "contradicted":
                claim.status = ClaimStatus.CONTRADICTED
                self.ledger.invalidate_dependents(claim.id)
            elif decision.target_status == "withdrawn":
                claim.status = ClaimStatus.WITHDRAWN
            else:
                claim.status = ClaimStatus.UNRESOLVED
            self.owner_last_refs[msg.thread] = set(msg.evidence)
        elif msg.act is Act.CHALLENGE and claim.status is ClaimStatus.PROPOSED:
            # Unverified critique does NOT establish the claim false.
            claim.status = ClaimStatus.UNRESOLVED
        self.events("message_delivered", claim_id=msg.thread,
                    message_id=msg.id, act=msg.act.value,
                    sender=self.bus.handle(msg.sender), status=claim.status.value)
        return result

    def begin_next_round(self) -> bool:
        if self.current_round and self.new_evidence == 0:
            return False
        self.current_round += 1
        self.new_evidence = 0
        return True

    def priority_order(self) -> list[str]:
        # Prefer uncertain, weakly grounded and unstable claims (no false 'strong' labels).
        rank = {ClaimStatus.UNRESOLVED: 0, ClaimStatus.PROPOSED: 1,
                ClaimStatus.SUPPORTED: 2}
        claims = [c for c in self.ledger.claims.values() if c.status in rank]
        return [c.id for c in sorted(claims,
                key=lambda c: (rank[c.status], bool(c.evidence_ids),
                               not c.needs_re_evaluation, c.id))]

    def flags(self, requirements=None):
        return deterministic_flags(self.ledger, requirements)

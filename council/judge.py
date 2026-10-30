"""Evidence-restricted, author-blind verdict input and failure handling."""
from __future__ import annotations
import json
from council.models import ClaimLedger, ClaimStatus

def blind_ledger(ledger: ClaimLedger, *, max_chars: int = 6500) -> str:
    records = [{
        "claim_id": c.id, "version": c.version,
        "statement": c.statement, "status": c.status.value,
        "evidence": [{
            "id": e.id, "kind": e.kind.value, "outcome": e.outcome,
            "scope": e.scope, "independently_checked": e.independently_checked}
            for evid in c.evidence_ids if (e := ledger.evidence.get(evid)) is not None],
        "depends_on": c.dependencies}
        for c in ledger.claims.values()]
    serialized = json.dumps(records, ensure_ascii=False)
    if len(serialized) > max_chars:
        # Never silently omit blockers or truncate assumptions.
        raise ValueError("Ledger exceeds judge context; split into explicit sub-questions")
    return serialized

def enforce_verdict(proposed: dict, ledger: ClaimLedger) -> dict:
    wanted = proposed.get("status")
    if wanted not in {"answer", "unresolved"}:
        wanted = "unresolved"
    blocking = sorted(c.id for c in ledger.claims.values()
                      if c.status is not ClaimStatus.SUPPORTED or c.needs_re_evaluation)
    if blocking:
        wanted = "unresolved"
    explicit = proposed.get("cause")
    hard_causes = {"judge_error", "composition_failure", "deadline", "quota_contention"}
    cause = (explicit if explicit in hard_causes else
             ("blocking_claims" if blocking else explicit))
    if explicit in hard_causes:
        wanted = "unresolved"
    return {"status": wanted,
            "answer": proposed.get("answer") if wanted == "answer" else None,
            "partial_answer": proposed.get("partial_answer") or proposed.get("answer"),
            "blocking": blocking, "basis": proposed.get("basis", []),
            "cause": cause}

def judge_failure(ledger: ClaimLedger, partial: str = "") -> dict:
    return enforce_verdict({"status":"unresolved", "answer":None,
                            "partial_answer":partial, "cause":"judge_error"}, ledger)

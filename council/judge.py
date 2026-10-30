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

def _substantive_text(value) -> str | None:
    """A model's literal 'null' or 'none' is not a research summary."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.casefold() in {
            "null", "none", "n/a", "undefined", "(none)", "no answer"}:
        return None
    return cleaned


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
    answer = _substantive_text(proposed.get("answer"))
    partial = _substantive_text(proposed.get("partial_answer")) or answer
    # JSON shape validation alone does not make the string "null" useful.
    if partial is None and wanted == "unresolved" and explicit is None:
        explicit = "judge_error"
    if answer is None and wanted == "answer":
        wanted = "unresolved"
        explicit = "judge_error"
    cause = (explicit if explicit in hard_causes else
             ("blocking_claims" if blocking else explicit))
    if explicit in hard_causes:
        wanted = "unresolved"
    return {"status": wanted,
            "answer": answer if wanted == "answer" else None,
            "partial_answer": partial,
            "blocking": blocking, "basis": proposed.get("basis", []),
            "cause": cause}


def judge_failure(ledger: ClaimLedger, partial: str = "") -> dict:
    return enforce_verdict({"status":"unresolved", "answer":None,
                            "partial_answer":partial, "cause":"judge_error"}, ledger)

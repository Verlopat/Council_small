"""Final answer composition can never silently promote claims."""
from __future__ import annotations
from dataclasses import dataclass
from council.models import ClaimLedger, ClaimStatus
from council.verify.arithmetic import check as arithmetic_check
from council.verify.sandbox import run_python

@dataclass(frozen=True)
class Composition:
    outcome: str
    blocking: tuple[str, ...]
    limitation: str

def compose_prose(asserted_claim_ids: list[str], ledger: ClaimLedger) -> Composition:
    blocking = tuple(cid for cid in asserted_claim_ids
                     if cid not in ledger.claims or
                     ledger.claims[cid].status is not ClaimStatus.SUPPORTED)
    return Composition("unchecked" if blocking else "scoped_support", blocking,
        "Prose entailment not mechanically established; all unsupported assertions must be marked uncertain")

def compose_numeric(expression: str, expected: int) -> Composition:
    result = arithmetic_check(expression, expected)
    return Composition(result.outcome, () if result.outcome == "pass" else ("assembled_number",),
                       "Explicit expression only; source assumptions remain unchecked")

def compose_code(assembled_check_code: str, *, timeout: float = 10) -> Composition:
    result = run_python(assembled_check_code, timeout=timeout)
    return Composition(result.outcome, () if result.outcome == "pass" else ("assembled_code",),
                       "Only checks performed by the isolated composition test are supported")

def compose_answer(answer: str, asserted_claim_ids: list[str],
                   ledger: ClaimLedger) -> Composition:
    """Verify the *assembled* answer where an exact check is possible.

    Numeric replies must match an independently supported arithmetic claim
    whose literal equation can be recomputed. Unanchored prose is left
    unchecked, even if its source claims are otherwise supported.
    """
    import re
    if not isinstance(answer, str) or not answer.strip():
        return Composition("unchecked", ("empty_composition",),
                           "Judge returned no answer to check")
    literal = answer.strip()
    if re.fullmatch(r"[+-]?\d+", literal):
        expected = int(literal)
        candidate_count = 0
        for cid in asserted_claim_ids:
            claim = ledger.claims.get(cid)
            if claim is None or claim.status is not ClaimStatus.SUPPORTED:
                continue
            match = re.fullmatch(r"\s*([^=]+?)\s*=\s*([+-]?\d+)\s*",
                                 claim.statement)
            if not match:
                continue
            expression, claimed_expected = match.groups()
            if int(claimed_expected) != expected:
                continue
            candidate_count += 1
            check = arithmetic_check(expression, expected)
            if check.outcome == "pass":
                return Composition("pass", (),
                    "Assembled integer recomputed from a supported literal equation; source assumptions unchanged")
        return Composition("unchecked", ("assembled_number",),
            "No supported literal equation recomputes the assembled integer")
    base = compose_prose(asserted_claim_ids, ledger)
    if base.blocking:
        return base
    supported_exact = {ledger.claims[cid].statement.strip()
                       for cid in asserted_claim_ids if cid in ledger.claims
                       and ledger.claims[cid].status is ClaimStatus.SUPPORTED}
    if literal in supported_exact:
        return Composition("scoped_support", (),
            "Exact supported statement only; informal meaning beyond its evidence scope is not proved")
    return Composition("unchecked", ("unmapped_prose",),
        "The final prose contains content not mechanically mapped to a supported atomic claim")

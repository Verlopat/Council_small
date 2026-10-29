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

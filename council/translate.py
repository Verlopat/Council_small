"""Select verification by *meaning and evidence scope*, not first available rung."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class VerificationPlan:
    claim_id: str
    claim_version: int
    claim_kind: str
    check_kind: str
    scope: str
    assumptions: tuple[str, ...]
    requires_independent_translation: bool = False

KINDS = {
    "arithmetic": "arithmetic",
    "program": "property_tests",
    "identity": "sympy",
    "satisfiability": "z3",
    "paper_description": "source_passage",
    "novelty": "literature_comparison",
    "research_feasibility": "prototype",
    "universal": "formal_proof_or_counterexample",
}

def plan(claim_id: str, version: int, kind: str, *, scope: str,
         assumptions: tuple[str, ...] = (), high_stakes: bool = False) -> VerificationPlan:
    if kind not in KINDS or version < 1 or not scope:
        raise ValueError("Unsupported claim semantics, scope or version")
    return VerificationPlan(claim_id, version, kind, KINDS[kind], scope,
                            assumptions, high_stakes)

def translation_independent(owner_family: str, translator_families: set[str],
                            *, high_stakes: bool) -> bool:
    candidates = translator_families - {owner_family}
    return len(candidates) >= (2 if high_stakes else 1)

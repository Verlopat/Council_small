"""Verifier-specification tests and mandatory mutation analysis in bwrap."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from council.verify.sandbox import run_python, SandboxResult
from council.verify.mutation import code_mutants, assess, MutationAssessment

@dataclass(frozen=True)
class CheckSpecification:
    statement: str
    code: str
    valid_examples: tuple[str, ...]
    invalid_examples: tuple[str, ...]
    limitation: str
    claim_version: int

    def __post_init__(self):
        if not self.statement.strip() or not self.limitation.strip():
            raise ValueError("A verification spec needs statement and scope/limitations")
        if not self.valid_examples or not self.invalid_examples:
            raise ValueError("Generated verifier needs positive and negative test cases")
        if self.claim_version < 1:
            raise ValueError("Invalid claim version")

@dataclass(frozen=True)
class CheckOutcome:
    outcome: str
    scope: str
    checker_hash: str
    mutation: MutationAssessment | None
    issue: str

def evaluate_spec(spec: CheckSpecification, *, timeout: float = 10,
                  mutant_limit: int = 6) -> CheckOutcome:
    digest = hashlib.sha256(spec.code.encode()).hexdigest()
    initial = run_python(spec.code, timeout=timeout)
    if initial.outcome not in {"pass", "fail"}:
        return CheckOutcome(initial.outcome, spec.limitation, digest, None, initial.detail)
    # Explicit fixtures must themselves print a pass boolean.
    for positive in spec.valid_examples:
        result = run_python(positive, timeout=timeout)
        if result.outcome != "pass":
            return CheckOutcome("checker_error", spec.limitation, digest, None,
                                "valid fixture rejected or failed to execute")
    for negative in spec.invalid_examples:
        result = run_python(negative, timeout=timeout)
        if result.outcome != "fail":
            return CheckOutcome("checker_error", spec.limitation, digest, None,
                                "invalid fixture was not rejected")
    mutants = code_mutants(spec.code, mutant_limit)
    assessment = assess(lambda text: run_python(text, timeout=timeout).outcome,
                        spec.code, mutants)
    if not assessment.discriminating:
        return CheckOutcome("inconclusive", spec.limitation, digest, assessment,
                            "mutation survived, equivalent mutant, or invalid mutant; inspect the test")
    return CheckOutcome(initial.outcome, spec.limitation, digest, assessment,
                        "Within stated check scope only; not a universal theorem proof")

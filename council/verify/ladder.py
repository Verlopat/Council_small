"""Verification is claim-specific and scoped. Unsupported kinds stay unresolved."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json

from council.translate import VerificationPlan
from council.verify.arithmetic import check as arithmetic_check
from council.verify.sympy_check import identity
from council.verify.z3_check import unsatisfiable
from council.verify.python_exec import evaluate_spec, CheckSpecification
from council.verify.source import PaperIndex

@dataclass(frozen=True)
class VerificationOutcome:
    outcome: str
    kind: str
    scope: str
    artifact_hash: str
    limitation: str

def verify(plan: VerificationPlan, artifact: dict, *,
           paper_index: PaperIndex | None = None) -> VerificationOutcome:
    digest = hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()
    try:
        if plan.check_kind == "arithmetic":
            result = arithmetic_check(artifact["expression"], artifact["expected"])
            return VerificationOutcome(result.outcome, "arithmetic", result.scope,
                                       digest, result.limitation)
        if plan.check_kind == "sympy":
            result = identity(artifact["left"], artifact["right"])
            return VerificationOutcome(result.outcome, "symbolic", plan.scope,
                                       digest, "Symbolic expressions checked inside sandbox")
        if plan.check_kind == "z3":
            result = unsatisfiable(artifact["assertions"])
            return VerificationOutcome(result.outcome, "smt", plan.scope, digest,
                                       "SMT assertions only, not source-claim correspondence")
        if plan.check_kind == "property_tests":
            spec = CheckSpecification(statement=plan.scope,
                code=artifact["code"],
                valid_examples=tuple(artifact["valid_examples"]),
                invalid_examples=tuple(artifact["invalid_examples"]),
                limitation=artifact["limitation"], claim_version=plan.claim_version)
            result = evaluate_spec(spec)
            return VerificationOutcome(result.outcome, "property_tests", plan.scope,
                                       digest, result.issue)
        if plan.check_kind == "source_passage":
            if paper_index is None:
                return VerificationOutcome("unresolved", "source", plan.scope, digest,
                                           "No trusted local corpus provided")
            result = paper_index.quote(artifact["document_id"], artifact["quote"])
            return VerificationOutcome("pass" if result.found else "unresolved",
                                       "quote_exists", result.scope, digest,
                                       "Quote existence does not establish semantic entailment")
    except (ValueError, TypeError, KeyError, OverflowError):
        return VerificationOutcome("error", plan.check_kind, plan.scope, digest,
                                   "Invalid verification artifact")
    return VerificationOutcome("unresolved", plan.check_kind, plan.scope, digest,
                "Requires additional formal proof, literature review or prototype evidence")

"""Verification is claim-specific and scoped. Unsupported kinds stay unresolved."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import re

from council.translate import VerificationPlan
from council.verify.arithmetic import check as arithmetic_check
from council.verify.sympy_check import identity
from council.verify.z3_check import unsatisfiable
from council.verify.python_exec import evaluate_spec, CheckSpecification
from council.verify.source import PaperIndex
from council.verify.domain import check as domain_check

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
            # Providers may use expected_int instead of expected.
            # Reject conflicting aliases rather than silently choosing one.
            keys=("expected","expected_int","expected_value",
                  "expected_result","result","value")
            values=[artifact[key] for key in keys if key in artifact]
            if not values:
                raise KeyError("expected")
            def as_int(value):
                if type(value) is int:
                    return value
                if isinstance(value,str):
                    raw=value.replace(",","").strip()
                    if re.fullmatch(r"[+-]?\d+",raw):
                        return int(raw)
                raise ValueError("Expected result must be an integer")
            expected=as_int(values[0])
            if any(as_int(x)!=expected for x in values[1:]):
                raise ValueError("Conflicting expected aliases")
            result = arithmetic_check(artifact["expression"], expected)
            return VerificationOutcome(result.outcome, "arithmetic", result.scope,
                                       digest, result.limitation)
        if plan.check_kind == "sympy":
            left=artifact.get("left",artifact.get("lhs"))
            right=artifact.get("right",artifact.get("rhs"))
            if left is None or right is None:
                raise KeyError("left/right")
            if ("left" in artifact and "lhs" in artifact
                    and left!=artifact["lhs"]) or (
                    "right" in artifact and "rhs" in artifact
                    and right!=artifact["rhs"]):
                raise ValueError("Conflicting symbolic aliases")
            result = identity(left, right)
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
        if plan.check_kind == "formal_proof_or_counterexample":
            tool = artifact.get("tool")
            source = artifact.get("source")
            if tool not in {"lean", "tamarin", "proverif"}:
                return VerificationOutcome(
                    "unresolved", "formal_proof", plan.scope, digest,
                    "A supported formal proof tool and exact formal source are required")
            if not isinstance(source, str) or not source.strip():
                return VerificationOutcome(
                    "error", "formal_proof", plan.scope, digest,
                    "Missing formal proof source")
            result = domain_check(tool, source, timeout=30)
            # This checks the submitted artifact, not its natural-language
            # correspondence; CouncilRunner does not promote it to independent
            # claim evidence without separate alignment.
            return VerificationOutcome(
                result.outcome, "formal_proof", plan.scope, digest,
                result.limitation + "; natural-language translation not certified")
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

"""Typed research records. Reviews are not proofs, and evidence is claim-version scoped."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import deque
from council.dependencies import Dependency, DependencyGraph


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"
    WITHDRAWN = "withdrawn"


class EvidenceKind(str, Enum):
    TEST = "test"
    FORMAL_PROOF = "formal_proof"
    SOURCE = "source"
    COUNTEREXAMPLE = "counterexample"
    MODEL_REVIEW = "model_review"


@dataclass(frozen=True)
class Evidence:
    id: str
    claim_id: str
    claim_version: int
    kind: EvidenceKind
    outcome: str
    scope: str
    artifact_hash: str
    assumptions: tuple[str, ...] = ()
    independently_checked: bool = False
    source_id: str | None = None
    provenance: tuple[str, ...] = ()
    checker_kind: str | None = None


@dataclass
class Claim:
    id: str
    version: int
    statement: str
    owner_family: str
    status: ClaimStatus = ClaimStatus.PROPOSED
    dependencies: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    needs_re_evaluation: bool = False
    source_span: str | None = None
    assumptions: list[str] = field(default_factory=list)
    quantifiers: list[str] = field(default_factory=list)
    scope: str | None = None
    artifact_hash: str | None = None

    def revise(self, statement: str) -> "Claim":
        """Revision invalidates the applicability of prior evidence."""
        if not statement.strip():
            raise ValueError("A claim needs a statement")
        return Claim(self.id, self.version + 1, statement, self.owner_family,
                     dependencies=list(self.dependencies),
                     limitations=list(self.limitations),
                     needs_re_evaluation=True,
                     source_span=self.source_span,
                     assumptions=list(self.assumptions),
                     quantifiers=list(self.quantifiers), scope=self.scope,
                     artifact_hash=None)


@dataclass(frozen=True)
class Objection:
    id: str
    proposal_id: str
    claim_id: str
    reviewer_family: str
    issue: str
    consequence: str
    suggested_check: str


@dataclass(frozen=True)
class AuthorResponse:
    objection_id: str
    disposition: str
    explanation: str
    evidence_ids: tuple[str, ...] = ()
    revised_claim_id: str | None = None

    def __post_init__(self):
        if self.disposition not in {"accept", "reject", "partial", "unresolved"}:
            raise ValueError("Invalid objection disposition")


@dataclass
class ResearchResult:
    research_question: str
    proposed_approach: str = ""
    supported_findings: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    unresolved_objections: list[str] = field(default_factory=list)
    proof_obligations: list[str] = field(default_factory=list)
    proposed_experiments: list[str] = field(default_factory=list)
    checked_source_ids: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    completion_status: str = "partial"
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ClaimLedger:
    """Single-writer in-memory ledger; evidence never silently follows edits."""
    def __init__(self):
        self.claims: dict[str, Claim] = {}
        self.evidence: dict[str, Evidence] = {}
        self.argument_dependencies = DependencyGraph()

    def add_claim(self, claim: Claim) -> None:
        if claim.id in self.claims:
            raise ValueError("Duplicate claim ID")
        if claim.version < 1 or not claim.statement.strip():
            raise ValueError("Invalid claim")
        self.claims[claim.id] = claim

    def register_dependency(self, edge: Dependency) -> None:
        self.argument_dependencies.add(edge, claims=self.claims)
        claim=self.claims[edge.dependent_id]
        if edge.premise_id not in claim.dependencies:
            claim.dependencies.append(edge.premise_id)

    def distinct_evidence_sources(self, claim_id: str) -> set[str]:
        """Two models citing one document remain ONE underlying source."""
        claim=self.claims[claim_id]
        sources=set()
        for identifier in claim.evidence_ids:
            item=self.evidence.get(identifier)
            if item is None or item.claim_version!=claim.version:
                continue
            sources.add(item.source_id or item.artifact_hash)
        return sources

    def attach(self, evidence: Evidence) -> None:
        claim = self.claims[evidence.claim_id]
        if evidence.claim_version != claim.version:
            raise ValueError("Stale evidence belongs to an older claim version")
        if evidence.id in self.evidence:
            raise ValueError("Duplicate evidence")
        self.evidence[evidence.id] = evidence
        claim.evidence_ids.append(evidence.id)
        # Passing tests are scoped support, not global proof.
        if (evidence.independently_checked and evidence.outcome == "pass"
                and evidence.kind in (EvidenceKind.TEST, EvidenceKind.FORMAL_PROOF)):
            claim.status = ClaimStatus.SUPPORTED
        elif (evidence.independently_checked and evidence.outcome == "fail"
                and evidence.kind in (EvidenceKind.TEST, EvidenceKind.COUNTEREXAMPLE)):
            claim.status = ClaimStatus.CONTRADICTED
            self.invalidate_dependents(claim.id)

    def revise(self, claim_id: str, new_text: str) -> Claim:
        claim = self.claims[claim_id].revise(new_text)
        self.claims[claim_id] = claim
        self.invalidate_dependents(claim_id)
        return claim

    def invalidate_dependents(self, premise_id: str) -> None:
        """Invalidate transitive arguments without declaring conclusions false."""
        affected=self.argument_dependencies.invalidate(premise_id)
        queue=deque([premise_id])
        seen={premise_id}
        # Also cover legacy plain-ID dependency edges for old persisted runs.
        while queue:
            parent=queue.popleft()
            for claim in self.claims.values():
                if parent in claim.dependencies and claim.id not in seen:
                    affected.add(claim.id)
                    seen.add(claim.id)
                    queue.append(claim.id)
        for cid in affected:
            dependent=self.claims.get(cid)
            if dependent is None:
                continue
            dependent.needs_re_evaluation=True
            if dependent.status == ClaimStatus.SUPPORTED:
                dependent.status = ClaimStatus.UNRESOLVED

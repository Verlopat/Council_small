"""First complete research milestone: sealed proposals -> peer critiques -> revisions -> synthesis -> audit.

The system does not upgrade a proposal to fact based on model agreement.
"""
from __future__ import annotations
import json
from dataclasses import asdict
from council.budget import RunBudget
from council.families import validate_assignment
from council.ledger import SQLiteLedger
from council.models import (Claim, ClaimLedger, Objection, AuthorResponse,
                            ResearchResult)
from council.parse import (OutputError, parse_object, require_string,
                           string_list, item_list)
from council.prompts import prompt
from council.schemas import validate as validate_output
from council.transport import FamilyUnavailable

DEFAULT_SOLVERS = ("gpt-oss", "command", "nemotron")
JUDGE = "gemini"
AUDITOR = "glm"

class CouncilRunner:
    def __init__(self, transport, events, budget: RunBudget, *,
                 solvers: tuple[str, ...] = DEFAULT_SOLVERS):
        validate_assignment(solvers, JUDGE, AUDITOR)
        self.transport = transport
        self.events = events
        self.budget = budget
        self.solvers = solvers
        self.ledger = ClaimLedger()
        self.warnings: list[str] = []
        self.actual_models: list[dict] = []

    async def _call(self, family: str, role: str, data: dict, *,
                    synthesis: bool = False) -> dict | None:
        if self.budget.allowed(30, synthesis=synthesis) <= 1:
            self.warnings.append(role + "/" + family + ": deadline reached")
            return None

        original_message = prompt(role, data)
        # Only proposals and judges get one bounded format retry. Retry
        # modifies formatting instructions, not the task, ledger or raw answer.
        # Never feed rejected model text back as privileged instructions.
        for attempt in range(2 if role in {"proposal", "judge"} else 1):
            if attempt:
                separator = "\nDATA_JSON:\n"
                if separator not in original_message:
                    self.warnings.append(role + "/" + family +
                                         ": format retry unavailable")
                    return None
                if role == "proposal":
                    formatting = (
                        "Output ONE complete JSON object with nonempty approach, "
                        "at least one anchored claim, hypotheses and experiments. "
                        "Every claim needs id, statement, source_span, assumptions, "
                        "limitations, depends_on and dependency_argument. "
                        "Source spans must be exact quotes from the approach. ")
                else:
                    formatting = (
                        "Output ONE complete JSON object for the blind judge. "
                        "Required: status equal to 'answer' or 'unresolved'. "
                        "Optional: answer, partial_answer (strings), blocking "
                        "and basis (arrays of strings). "
                        "Do not promote unsupported claims to established facts. ")
                message = original_message.replace(
                    separator, "\nFORMAT RETRY: Previous generation did not "
                    "satisfy this role's JSON contract. " + formatting +
                    "No markdown, commentary, or fabricated evidence.\n" +
                    separator, 1)
            else:
                message = original_message
            try:
                response = await self.transport.complete(
                    family, message, self.budget, role=role,
                    synthesis=synthesis)
            except FamilyUnavailable as exc:
                self.warnings.append(role + "/" + family + ": " + "; ".join(exc.failures))
                self.events.record("role_unavailable", role=role, family=family,
                                   failures=exc.failures)
                return None
            self.actual_models.append({"role": role, "family": family,
                                       "provider": response.provider,
                                       "model": response.model,
                                       "prompt_hash": response.prompt_hash})
            try:
                return validate_output(role, parse_object(response.text))
            except (OutputError, ValueError) as error:
                # Never print raw user prompts or provider text in diagnostics;
                # output/schema error strings describe only parser constraints.
                reason = str(error).splitlines()[0][:180]
                self.events.record("role_parse_error", role=role, family=family,
                                   provider=response.provider, model=response.model,
                                   reason=reason, attempt=attempt + 1)
                if (role in {"proposal", "judge"} and attempt == 0 and
                        self.budget.allowed(30, synthesis=synthesis) > 2):
                    self.events.record("format_retry_requested",
                                       role=role, family=family,
                                       failed_model=response.model,
                                       reason=reason)
                    continue
                self.warnings.append(role + "/" + family +
                                     ": invalid structured output (" + reason + ")")
                return None
        return None

    def _proposal(self, family: str, body: dict, index: int) -> dict:
        approach = require_string(body, "approach")
        raw_claims = item_list(body, "claims")
        if not raw_claims:
            raise OutputError("Proposal must include at least one claim")
        proposal_id = "p" + str(index)
        claim_map: dict[str, str] = {}
        for j, raw in enumerate(raw_claims, 1):
            local = require_string(raw, "id")
            statement = require_string(raw, "statement")
            if local in claim_map:
                raise OutputError("Duplicate local claim id")
            cid = proposal_id + ":c" + str(j)
            claim_map[local] = cid
            self.ledger.add_claim(Claim(
                id=cid, version=1, statement=statement, owner_family=family,
                limitations=string_list(raw, "limitations")))
        return {"id": proposal_id, "family": family, "approach": approach,
                "claim_ids": list(claim_map.values()), "claim_map": claim_map,
                "hypotheses": string_list(body, "hypotheses"),
                "experiments": string_list(body, "experiments")}

    async def run(self, question: str, *, mode: str = "research") -> dict:
        if mode not in {"quick", "research"}:
            raise ValueError("mode must be quick or research")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("The research question must not be empty")
        active = self.solvers[:1] if mode == "quick" else self.solvers
        self.events.record("run_started", question=question, mode=mode,
                           solver_families=list(active), judge_family=JUDGE,
                           auditor_family=AUDITOR)
        proposals: list[dict] = []
        objections: list[Objection] = []
        replies: list[AuthorResponse] = []
        for i, family in enumerate(active, 1):
            body = await self._call(family, "proposal", {"question": question,
                                    "independent": True})
            if body is None:
                continue
            try:
                p = self._proposal(family, body, i)
            except (OutputError, ValueError) as exc:
                self.warnings.append(family + ": invalid proposal schema: " + str(exc))
                continue
            proposals.append(p)
            self.events.record("proposal_received", proposal=p)
        # No agent sees anyone else's first-round answer until all proposals finish.
        if mode == "research" and len(proposals) >= 2:
            for index, p in enumerate(proposals):
                reviewer = proposals[(index + 1) % len(proposals)]["family"]
                if reviewer == p["family"] or reviewer == JUDGE:
                    continue
                body = await self._call(reviewer, "review", {
                    "question": question, "proposal": p,
                    "claims": [asdict(self.ledger.claims[cid])
                               for cid in p["claim_ids"]]})
                if body is None:
                    continue
                try:
                    items = item_list(body, "objections")
                    for raw in items:
                        local_id = require_string(raw, "claim_id")
                        cid = p["claim_map"].get(local_id, local_id)
                        if cid not in p["claim_ids"]:
                            self.warnings.append("Dropped review with unknown claim id")
                            continue
                        objection = Objection(
                            id="o" + str(len(objections) + 1),
                            proposal_id=p["id"], claim_id=cid,
                            reviewer_family=reviewer,
                            issue=require_string(raw, "issue"),
                            consequence=require_string(raw, "consequence"),
                            suggested_check=require_string(raw, "suggested_check"))
                        objections.append(objection)
                        self.events.record("review_received", objection=asdict(objection))
                except OutputError:
                    self.warnings.append("Rejected malformed review from " + reviewer)
            for p in proposals:
                related = [o for o in objections if o.proposal_id == p["id"]]
                if not related:
                    continue
                body = await self._call(p["family"], "revision", {
                    "original_approach": p["approach"],
                    "claims": [asdict(self.ledger.claims[cid]) for cid in p["claim_ids"]],
                    "objections": [asdict(o) for o in related]})
                if body is None:
                    continue
                try:
                    p["revised_approach"] = require_string(body, "revised_approach")
                    for raw in item_list(body, "revised_claims"):
                        cid = require_string(raw, "claim_id")
                        if cid not in p["claim_ids"]:
                            continue
                        claim = self.ledger.revise(cid, require_string(raw, "statement"))
                        self.events.record("claim_revised", claim_id=cid,
                                           new_version=claim.version)
                    for raw in item_list(body, "responses"):
                        oid = require_string(raw, "objection_id")
                        if oid not in {o.id for o in related}:
                            continue
                        response = AuthorResponse(
                            objection_id=oid, disposition=require_string(raw, "disposition"),
                            explanation=require_string(raw, "explanation"))
                        replies.append(response)
                        self.events.record("author_response_received", response=asdict(response))
                except (OutputError, ValueError):
                    self.warnings.append("Rejected malformed revision from " + p["family"])

        brief = ResearchResult(research_question=question,
                               completion_status="partial" if proposals else "unresolved")
        brief.hypotheses = list(dict.fromkeys(
            hypothesis for p in proposals for hypothesis in p["hypotheses"]))
        brief.proposed_experiments = list(dict.fromkeys(
            experiment for p in proposals for experiment in p["experiments"]))
        brief.unresolved_objections = [
            o.issue + " [claim " + o.claim_id + ", " + o.id + "]" for o in objections]
        brief.proposed_approach = " | ".join(
            p.get("revised_approach", p["approach"]) for p in proposals)
        brief.limitations = list(self.warnings)

        if proposals:
            synthesis = await self._call(JUDGE, "synthesis", {
                "question": question, "proposals": proposals,
                "claims": [asdict(c) for c in self.ledger.claims.values()],
                "objections": [asdict(o) for o in objections],
                "author_responses": [asdict(r) for r in replies],
                "verified_evidence": [],
                "rule": "No executed checks or retrieved sources: no supported findings",
            }, synthesis=True)
            if synthesis:
                try:
                    brief.proposed_approach = require_string(synthesis, "proposed_approach")
                    # The judge's unsupported findings remain hypotheses.
                    inferred = string_list(synthesis, "supported_findings")
                    if inferred:
                        brief.limitations.append(
                            "Judge-proposed findings were reclassified as unverified hypotheses")
                    brief.hypotheses = list(dict.fromkeys(
                        brief.hypotheses + string_list(synthesis, "hypotheses") + inferred))
                    brief.unresolved_objections = list(dict.fromkeys(
                        brief.unresolved_objections +
                        string_list(synthesis, "unresolved_objections")))
                    brief.proof_obligations = string_list(synthesis, "proof_obligations")
                    brief.proposed_experiments = list(dict.fromkeys(
                        brief.proposed_experiments +
                        string_list(synthesis, "proposed_experiments")))
                    brief.next_actions = string_list(synthesis, "next_actions")
                    self.events.record("synthesis_received", family=JUDGE)
                except OutputError:
                    brief.limitations.append("Synthesis schema invalid; deterministic partial preserved")
            else:
                brief.limitations.append("Judge unavailable; deterministic partial preserved")
        else:
            brief.limitations.append("No validated independent proposal obtained")

        if mode == "research" and proposals:
            audit = await self._call(AUDITOR, "audit", {
                "question": question, "brief": brief.to_dict(),
                "claims": [asdict(c) for c in self.ledger.claims.values()],
                "objections": [asdict(o) for o in objections],
            }, synthesis=True)
            if audit:
                try:
                    brief.unresolved_objections.extend(string_list(audit, "issues"))
                    brief.proposed_experiments.extend(string_list(audit, "suggested_checks"))
                    self.events.record("audit_received", family=AUDITOR)
                except OutputError:
                    brief.limitations.append("Audit schema invalid")
            else:
                brief.limitations.append("Independent audit unavailable")

        # No verifier was executed: neither a reviewer nor a judge can certify a finding.
        brief.supported_findings = []
        brief.checked_source_ids = []
        brief.completion_status = "partial" if proposals else "unresolved"
        brief.limitations = list(dict.fromkeys(brief.limitations + self.warnings))
        result = {
            "research_result": brief.to_dict(), "proposals": proposals,
            "objections": [asdict(o) for o in objections],
            "author_responses": [asdict(r) for r in replies],
            "claims": [asdict(c) for c in self.ledger.claims.values()],
            "actual_models": self.actual_models, "warnings": self.warnings,
        }
        # Enum subclasses of str and dataclasses are JSON serializable via asdict.
        if hasattr(self.events,"db") and hasattr(self.events,"run_id"):
            SQLiteLedger(self.events.db).save(self.events.run_id,self.ledger)
        self.events.record("run_finished", result=result)
        return result

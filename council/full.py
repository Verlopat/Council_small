"""Full P0-P6 evidence-aware Council pipeline.

All model suggestions remain unverified until a scoped checker returns evidence.
The architecture's later corrections override the unsafe weak/strong verdicts.
"""
from __future__ import annotations
import asyncio
from dataclasses import asdict
import hashlib
import json
import time

from council.assignment import Assignment
from council.dependencies import Dependency
from council.bus import MessageCap, MessageBus
from council.evidence import EvidenceRejected
from council.extract import validate_anchor, suggest_duplicate_claims
from council.judge import blind_ledger, enforce_verdict, judge_failure
from council.ledger import SQLiteLedger
from council.models import Claim, ClaimStatus, Evidence, EvidenceKind, ResearchResult, Objection, AuthorResponse
from council.moderator import Moderator
from council.protocol import Message, Act
from council.parse import item_list, string_list, require_string, OutputError
from council.translate import plan, decisive_if_supported
from council.verify.ladder import verify
from council.compose import compose_answer
from council.workflow import CouncilRunner
from council.requirements import Requirements

# Four-solvers variant would leave no reliable independently reserved auditing
# family given the currently configured MiniMax limitation, so default to three.
# The optional 4th solver is only enabled if an independent auditor is designated.
FULL_SOLVERS=("gpt-oss","command","nemotron")
TRANSLATOR="glm"
JUDGE="gemini"
AUDITOR="gemma"

class FullCouncilRunner(CouncilRunner):
    def __init__(self,transport,events,budget,*,requirements:Requirements|None=None,
                 solvers=FULL_SOLVERS,max_claims=12,hunter_cap=4,
                 translator_family=TRANSLATOR,judge_family=JUDGE,
                 auditor_family=AUDITOR,enable_coverage=True,
                 enable_relevance=False,critics=(),adaptive_seeds=False,
                 enable_repairs=True, caps=None, paper_index=None,
                 solver_strategies=None):
        super().__init__(transport,events,budget,solvers=tuple(solvers))
        self.assignment=Assignment(tuple(solvers),translator=translator_family,
                                   judge=judge_family,auditor=auditor_family)
        self.translator_family=translator_family
        self.judge_family=judge_family
        self.auditor_family=auditor_family
        self.requirements=requirements
        defaults = {"messages": 5, "verifier_calls": 2,
                    "repairs": 1, "pair_exchanges": 3}
        self.caps = dict(defaults)
        self.caps.update(caps or {})
        if set(self.caps) != set(defaults) or any(
                type(n) is not int or n < 1 or n > 20
                for n in self.caps.values()):
            raise ValueError("Invalid debate caps")
        bus = MessageBus(message_cap=self.caps["messages"],
                         verifier_cap=self.caps["verifier_calls"],
                         repair_cap=self.caps["repairs"],
                         pair_cap=self.caps["pair_exchanges"])
        self.moderator=Moderator(self.ledger,bus=bus,events=events.record)
        defaults_strategies = {"gpt-oss":"direct", "command":"code",
                               "nemotron":"decompose", "gemma":"code"}
        self.solver_strategies = {
            f: (solver_strategies or {}).get(f, defaults_strategies.get(f,"direct"))
            for f in self.solvers}
        if any(strategy not in {"direct","code","decompose"}
               for strategy in self.solver_strategies.values()):
            raise ValueError("Unsupported solver strategy")
        self.max_claims=max_claims
        self.hunter_cap=hunter_cap
        self.coverage=[]
        self.verified=[]
        self.enable_coverage=bool(enable_coverage)
        self.enable_relevance=bool(enable_relevance)
        self.critics=tuple(critics)
        self.adaptive_seeds=bool(adaptive_seeds)
        self.enable_repairs=bool(enable_repairs)
        self.paper_index=paper_index
        self.checked_sources=set()
        self.extra_obligations=[]
        self.objections=[]
        self.author_responses=[]

    def _anchors(self,p:dict,body:dict)->None:
        # Only text authored in this proposal can establish provenance. A
        # statement appearing later in the blind judge answer is not an anchor.
        sources=[("approach",p["approach"])]
        answer=body.get("answer")
        if isinstance(answer,str) and answer and answer!=p["approach"]:
            sources.append(("answer",answer))
        for raw,cid in zip(item_list(body,"claims"),p["claim_ids"]):
            claim=self.ledger.claims[cid]
            declared_span=raw.get("source_span") or raw.get("span")
            assumptions=string_list(raw,"assumptions")
            anchored=None
            reason="no_exact_source_span"
            recovered=False
            for source_name,source_text in sources:
                candidates=[]
                if isinstance(declared_span,str) and declared_span.strip():
                    candidates.append(declared_span)
                # The only auto-repair is a *verbatim* statement already in
                # the original response. Never infer paraphrase equivalence.
                if claim.statement in source_text and claim.statement not in candidates:
                    candidates.append(claim.statement)
                for candidate in candidates:
                    try:
                        anchored=validate_anchor(
                            source_text,claim.statement,candidate,
                            assumptions=assumptions)
                        recovered=candidate!=declared_span
                        break
                    except ValueError as exc:
                        reason=("quantifier_or_modality_mismatch"
                                if "Quantifier or modality" in str(exc)
                                else "source_span_not_exact")
                if anchored is not None:
                    if recovered or source_name!="approach":
                        self.events.record("claim_anchor_recovered",claim_id=cid,
                            method="verbatim_statement_or_original_answer",
                            source_field=source_name)
                    break
            if anchored is None:
                self.warnings.append(cid+": source anchoring failed ("+reason+")")
                self.events.record("claim_anchor_rejected",claim_id=cid,
                                   reason=reason)
                self.extra_obligations.append(
                    cid+": provide an exact quote from the original proposal")
                continue
            claim.source_span=anchored.source_span
            claim.assumptions=list(anchored.assumptions)
            claim.quantifiers=list(anchored.quantifiers)

    def _register_declared_dependencies(self, proposal: dict, body: dict) -> None:
        """Only register provenance when the model supplies the actual argument.

        Missing premises or argument text cannot be silently promoted into a
        confirmed proof edge. Cycles and stale claim references are rejected by
        DependencyGraph; no status is upgraded by a dependency alone.
        """
        claim_map = proposal["claim_map"]
        try:
            rows = item_list(body, "claims")
        except OutputError:
            return
        for row in rows:
            local_id = row.get("id")
            if not isinstance(local_id, str) or local_id not in claim_map:
                continue
            dependent = self.ledger.claims[claim_map[local_id]]
            references = row.get("depends_on", [])
            if not isinstance(references, list) or any(
                    not isinstance(ref, str) for ref in references):
                self.warnings.append(dependent.id + ": malformed dependency list")
                continue
            if not references:
                continue
            argument = row.get("dependency_argument")
            if not isinstance(argument, str) or not argument.strip():
                self.extra_obligations.append(
                    dependent.id + ": a dependency argument must be supplied")
                continue
            for ref in references:
                premise_id = claim_map.get(ref)
                if premise_id is None:
                    self.warnings.append(
                        dependent.id + ": unknown premise reference " + ref)
                    continue
                premise = self.ledger.claims[premise_id]
                edge = Dependency(premise.id, premise.version,
                                  dependent.id, dependent.version,
                                  argument=argument.strip(),
                                  valid_support=False)
                # Declaration records a candidate argument, NOT valid support.
                # Register as inactive until a qualified verifier confirms the edge.
                try:
                    self.ledger.register_dependency(edge)
                    self.events.record("dependency_declared",
                                       premise_id=premise.id, dependent_id=dependent.id,
                                       premise_version=premise.version,
                                       dependent_version=dependent.version,
                                       valid_support=False)
                except ValueError as exc:
                    self.warnings.append(
                        dependent.id + ": dependency rejected (" + str(exc) + ")")

    async def _translate_and_check(self,claim:Claim):
        if not claim.source_span:
            self.extra_obligations.append("Add an exact source span for "+claim.id)
            return
        if self.budget.debate_remaining()<=1:return
        proposal=await self._call(self.translator_family,"translate",{
            "claim_id":claim.id,"claim_version":claim.version,
            "statement":claim.statement,"source_span":claim.source_span,
            "assumptions":claim.assumptions,
            "rule":"A check must match the meaning of the claim"})
        if not proposal:return
        if proposal.get("rung") is None and not proposal.get("artifact"):
            self.moderator.bus.close(claim.id, "no_evidence_possible")
            self.events.record("stalemate", claim_id=claim.id,
                               cause="no_evidence_possible")
            self.extra_obligations.append(
                claim.id + ": translator supplied no discriminating check")
            return
        kind=proposal.get("claim_kind")
        scope=proposal.get("scope")
        artifact=proposal.get("artifact") or {}
        if not isinstance(kind,str) or not isinstance(scope,str) or not isinstance(artifact,dict):
            self.warnings.append("Malformed translator response for "+claim.id)
            return
        try:
            check_plan=plan(claim.id,claim.version,kind,scope=scope,
                            assumptions=tuple(claim.assumptions))
            result=await asyncio.to_thread(
                verify, check_plan, artifact, paper_index=self.paper_index)
        except (ValueError,TypeError,KeyError):
            self.warnings.append("Checker plan rejected for "+claim.id)
            return
        self.events.record("verification_attempt",claim_id=claim.id,
                           claim_version=claim.version,kind=kind,
                           scope=result.scope,outcome=result.outcome,
                           artifact_hash=result.artifact_hash,
                           limitation=result.limitation)
        if result.outcome not in {"pass","fail"}:
            self.extra_obligations.append(claim.id+": "+result.limitation)
            return
        # High-stakes means that, in a dry run, this claim is the last
        # remaining blocker. Check a second non-owner family before relying
        # on a translated artifact. Agreement is logged but never promoted
        # into independent formal claim-to-prose correctness.
        if (result.outcome == "pass" and result.kind != "arithmetic"
                and decisive_if_supported(self.ledger, claim.id)):
            second_family = next(
                (f for f in self.solvers
                 if f not in {claim.owner_family, self.translator_family,
                              self.judge_family, self.auditor_family}), None)
            if second_family and self.budget.debate_remaining() > 3:
                secondary = await self._call(second_family, "translate", {
                    "claim_id": claim.id,
                    "claim_version": claim.version,
                    "statement": claim.statement,
                    "source_span": claim.source_span,
                    "assumptions": claim.assumptions,
                    "independent_second_translation": True})
                if secondary:
                    secondary_artifact = secondary.get("artifact")
                    if (secondary.get("claim_kind") == kind
                            and secondary.get("scope") == scope
                            and isinstance(secondary_artifact, dict)):
                        secondary_plan = plan(
                            claim.id, claim.version, kind, scope=scope,
                            assumptions=tuple(claim.assumptions),
                            high_stakes=True)
                        secondary_result = await asyncio.to_thread(
                            verify, secondary_plan, secondary_artifact)
                        self.events.record(
                            "decisive_second_translation", claim_id=claim.id,
                            first_family=self.translator_family,
                            second_family=second_family,
                            first_outcome=result.outcome,
                            second_outcome=secondary_result.outcome,
                            matching_scope=True)
                        if secondary_result.outcome != result.outcome:
                            self.extra_obligations.append(
                                claim.id + ": independent translations disagree")
                    else:
                        self.extra_obligations.append(
                            claim.id + ": second translation disagrees on semantics or scope")
                else:
                    self.extra_obligations.append(
                        claim.id + ": second translation unavailable")
            else:
                self.extra_obligations.append(
                    claim.id + ": no independent second translator within budget")
        # A passing equation/source quote is NOT a security theorem proof.
        evidence_kind=(EvidenceKind.SOURCE if result.kind=="quote_exists"
                       else EvidenceKind.FORMAL_PROOF if result.kind=="formal_proof"
                       else EvidenceKind.TEST)
        independent=(result.kind=="arithmetic" and
                     self._literal_arithmetic_alignment(claim.statement,artifact))
        if evidence_kind is EvidenceKind.SOURCE:
            independent=False
            document_id=artifact.get("document_id")
            if isinstance(document_id,str) and document_id.strip():
                self.checked_sources.add(document_id)
                self.events.record(
                    "source_passage_checked", claim_id=claim.id,
                    document_id=document_id, artifact_hash=result.artifact_hash,
                    semantic_entailment="unchecked")
            if self.enable_relevance and self.budget.debate_remaining()>3:
                reviewer=next((f for f in self.solvers if f!=claim.owner_family),None)
                if reviewer:
                    opinion=await self._call(reviewer,"relevance",{
                        "claim_id":claim.id,"statement":claim.statement,
                        "scope":result.scope,"evidence_kind":result.kind})
                    self.events.record("relevance_opinion",claim_id=claim.id,
                        reviewer_family=reviewer,opinion=opinion or {})
        evidence=Evidence(
            id="e"+str(len(self.ledger.evidence)+1),claim_id=claim.id,
            claim_version=claim.version,kind=evidence_kind,
            outcome=result.outcome,scope=result.scope,
            artifact_hash=result.artifact_hash,
            assumptions=tuple(claim.assumptions),
            independently_checked=independent,
            checker_kind=result.kind)
        if independent:
            self.moderator.record_result(evidence)
            self.verified.append({"claim_id":claim.id,"evidence_id":evidence.id,
                                  "outcome":result.outcome,"scope":result.scope})
        else:
            # Preserve scoped checks but don't let an LLM-provided translation
            # certify its own correspondence to natural-language claim.
            self.ledger.attach(evidence)
            self.events.record("evidence_recorded",evidence_id=evidence.id,
                               claim_id=claim.id,outcome=result.outcome,
                               independently_checked=False)
            self.extra_obligations.append(
                claim.id+": independent claim-to-check alignment required")

    @staticmethod
    def _literal_arithmetic_alignment(statement,artifact):
        import re
        match=re.fullmatch(r"\s*([^=]+)\s*=\s*([+-]?\d+)\s*",statement)
        return (bool(match) and match.group(1).strip()==str(artifact.get("expression","")).strip()
                and str(artifact.get("expected"))==match.group(2))

    async def _extract_rival(self,owner,other_family):
        answer=owner.get("answer") or owner["approach"]
        result=await self._call(other_family,"extract",{
            "answer":answer,
            "listed_claims":[self.ledger.claims[cid].statement
                             for cid in owner["claim_ids"]],
            "owner_family_hidden":True})
        if not result:return
        try: raws=item_list(result,"claims")
        except OutputError:return
        for entry in raws[:self.max_claims]:
            try:
                statement=require_string(entry,"statement")
                span=require_string(entry,"source_span")
                anchored=validate_anchor(answer,statement,span,
                           assumptions=string_list(entry,"assumptions"))
            except (OutputError,ValueError):
                continue
            if any(c.statement==statement and c.assumptions==list(anchored.assumptions)
                   for c in self.ledger.claims.values()):
                continue
            cid=owner["id"]+":r"+str(len(self.ledger.claims)+1)
            c=Claim(cid,1,statement,owner["family"],source_span=span,
                    assumptions=list(anchored.assumptions),
                    quantifiers=list(anchored.quantifiers))
            self.ledger.add_claim(c)
            owner["claim_ids"].append(cid)
            self.events.record("rival_claim_extracted",claim_id=cid,
                               reviewer_family=other_family,source_span=span)

    async def _hunt_batch(self, jobs: list[tuple[Claim, str, int]]) -> None:
        """Run independent hunter inference concurrently, commit messages in stable order.

        The event-loop receives model proposals in parallel, but a *single*
        coordinator processes their effects on the claim ledger and bus. A model
        returning earlier must not gain a scheduling or truth advantage.
        """
        admissible = [(claim, family, round_number)
                      for claim, family, round_number in jobs
                      if family != claim.owner_family and
                      family not in {self.judge_family, self.auditor_family}
                      and self.budget.debate_remaining() > 1]
        if not admissible:
            return
        results = await asyncio.gather(*[
            self._call(family, "hunter", {
                "claim": claim.statement, "assumptions": claim.assumptions,
                "scope": claim.scope, "claim_id": claim.id})
            for claim, family, _ in admissible
        ])
        for (claim, hunter_family, round_number), result in zip(admissible, results):
            if not result or not result.get("found"):
                if result is not None:
                    previous = self.moderator.bus.stalemates().get(claim.id)
                    if previous is None:
                        self.moderator.bus.close(claim.id, "agents_gave_up")
                        self.events.record("stalemate", claim_id=claim.id,
                                           cause="agents_gave_up",
                                           hunter_family=hunter_family)
                    else:
                        self.events.record("hunter_abstained", claim_id=claim.id,
                                           hunter_family=hunter_family,
                                           prior_stalemate_cause=previous)
                continue
            detail = result.get("counterexample")
            if not isinstance(detail, str) or not detail.strip():
                continue
            message = Message("h" + str(len(self.moderator.bus.threads) + 1) +
                              ":" + claim.id, claim.id, Act.CHALLENGE,
                              hunter_family, hunter_family, detail[:2400],
                              step_ref=detail[:300], round=round_number)
            try:
                accepted = self.moderator.submit(message)
                if accepted == "accepted":
                    self.events.record("hunter_objection", claim_id=claim.id,
                                       hunter_family=hunter_family, issue=detail,
                                       round=round_number)
            except (EvidenceRejected, MessageCap):
                self.warnings.append("Hunter cap or evidence policy rejected " + claim.id)

    async def _hunt(self, claim: Claim, hunter_family: str, round_number: int) -> None:
        await self._hunt_batch([(claim, hunter_family, round_number)])

    async def run(self,question:str,*,mode:str="full")->dict:
        if not isinstance(question,str) or not question.strip():
            raise ValueError("Question required")
        req=self.requirements or Requirements(question)
        self.events.record("run_started",question=question,mode=mode,
            pipeline="evidence",
            requirements=req.as_data(),role_assignment=asdict(self.assignment),
            debate_caps=self.caps, solver_strategies=self.solver_strategies,
            deadline_remaining=self.budget.remaining())
        proposals=[]
        raw=await asyncio.gather(*[
            self._call(family,"proposal",{
                "question":question,"requirements":req.as_data(),
                "independent":True,"source_spans_required":True,
                "strategy":self.solver_strategies[family]})
            for family in self.solvers])
        for index,(family,body) in enumerate(zip(self.solvers,raw),1):
            if body is None:continue
            try:
                p=self._proposal(family,body,index)
                self._anchors(p,body)
                self._register_declared_dependencies(p,body)
                p["answer"]=body.get("answer") if isinstance(body.get("answer"),str) else p["approach"]
            except (OutputError,ValueError):
                self.warnings.append(family+": proposal failed validation")
                continue
            proposals.append(p)
            self.events.record("proposal_received",proposal=p)
        # Sealed stage ends only after all proposal calls have returned.
        if not proposals:
            result={"research_result":ResearchResult(question,completion_status="unresolved",
                    limitations=self.warnings).to_dict(),
                    "proposals":[],"claims":[],"warnings":self.warnings}
            if hasattr(self.events,"db") and hasattr(self.events,"run_id"):
                SQLiteLedger(self.events.db).save(self.events.run_id,self.ledger)
            self.events.record("run_finished",result=result)
            return result
        for i,p in enumerate(proposals):
            if self.budget.debate_remaining()<1:break
            peer=proposals[(i+1)%len(proposals)]["family"] if len(proposals)>1 else None
            if peer and peer!=p["family"]:
                await self._extract_rival(p,peer)
        # Similar wording suggests review candidates, never automatic proof
        # equivalence or a merge of distinct scope/assumptions.
        self.duplicate_suggestions = suggest_duplicate_claims(
            self.ledger.claims.values())
        if self.duplicate_suggestions:
            self.events.record("duplicate_claims_suggested",
                               candidates=self.duplicate_suggestions)
        # Independent peer review is not evidence. Authors may respond, but
        # only the reviewer or a verifier can establish a correction.
        for i,p in enumerate(proposals):
            if len(proposals)<2 or self.budget.debate_remaining()<=1:break
            peer=proposals[(i+1)%len(proposals)]["family"]
            if peer==p["family"]:continue
            review=await self._call(peer,"review",{
                "question":question,"proposal":{"id":p["id"],"approach":p["approach"]},
                "claims":[{"id":cid,"statement":self.ledger.claims[cid].statement}
                          for cid in p["claim_ids"]]})
            if not review:continue
            try: rows=item_list(review,"objections")
            except OutputError:continue
            for raw_ob in rows:
                try:
                    claimed=require_string(raw_ob,"claim_id")
                    cid=p["claim_map"].get(claimed,claimed)
                    if cid not in p["claim_ids"]:continue
                    obj=Objection("o"+str(len(self.objections)+1),p["id"],cid,peer,
                        require_string(raw_ob,"issue"),
                        require_string(raw_ob,"consequence"),
                        require_string(raw_ob,"suggested_check"))
                except (OutputError,ValueError):
                    continue
                self.objections.append(obj)
                self.events.record("review_received",objection=asdict(obj))
                try:
                    self.moderator.submit(Message("review:"+obj.id,cid,Act.CHALLENGE,
                        peer,peer,obj.issue[:2400],step_ref=obj.issue[:300]))
                except (EvidenceRejected,MessageCap):
                    self.warnings.append("Review challenge not delivered: "+obj.id)
        for p in proposals:
            if self.budget.debate_remaining()<=1:break
            related=[o for o in self.objections if o.proposal_id==p["id"]]
            if not related:continue
            author=await self._call(p["family"],"revision",{
                "original_approach":p["approach"],
                "claims":[{"id":cid,"statement":self.ledger.claims[cid].statement}
                          for cid in p["claim_ids"]],
                "objections":[asdict(o) for o in related]})
            if not author:continue
            try:
                if isinstance(author.get("revised_approach"),str):
                    p["revised_approach"]=author["revised_approach"]
                for item in item_list(author,"revised_claims"):
                    cid=require_string(item,"claim_id")
                    if cid not in p["claim_ids"]:continue
                    changed=require_string(item,"statement")
                    if changed!=self.ledger.claims[cid].statement:
                        revised=self.ledger.revise(cid,changed)
                        revised.source_span=None  # never inherit the old anchor
                        source_span=item.get("source_span")
                        updated_text=p.get("revised_approach","")
                        if isinstance(source_span,str) and isinstance(updated_text,str):
                            try:
                                anchor=validate_anchor(updated_text,changed,source_span,
                                    assumptions=string_list(item,"assumptions"))
                                revised.source_span=anchor.source_span
                                revised.assumptions=list(anchor.assumptions)
                                revised.quantifiers=list(anchor.quantifiers)
                            except (ValueError,OutputError):
                                self.warnings.append(cid+": revised claim anchor/quantifier mismatch")
                        if revised.source_span is None:
                            self.extra_obligations.append(cid+": revised statement needs a new exact source anchor")
                        self.events.record("claim_revised",claim_id=cid,version=revised.version,
                                           source_anchor_verified=bool(revised.source_span))
                for item in item_list(author,"responses"):
                    oid=require_string(item,"objection_id")
                    if oid not in {o.id for o in related}:continue
                    response=AuthorResponse(oid,require_string(item,"disposition"),
                                            require_string(item,"explanation"))
                    self.author_responses.append(response)
                    self.events.record("author_response_received",response=asdict(response))
            except (OutputError,ValueError):
                self.warnings.append("Invalid author revision by "+p["family"])
        # The original critic re-reads the author's revised text without
        # being allowed to close its own objection by consensus.
        for p in proposals:
            if "revised_approach" not in p or self.budget.debate_remaining()<3:
                continue
            reviewer=next((f for f in self.solvers if f!=p["family"]),None)
            if not reviewer:
                continue
            followup=await self._call(reviewer,"review",{
                "question":question,"proposal":{"id":p["id"],
                    "approach":p["revised_approach"]},
                "claims":[{"id":cid,"statement":self.ledger.claims[cid].statement,
                           "source_span":self.ledger.claims[cid].source_span}
                          for cid in p["claim_ids"]],
                "review_phase":"independent_revision_recheck"})
            if followup:
                try:
                    for raw_ob in item_list(followup,"objections"):
                        claimed=require_string(raw_ob,"claim_id")
                        cid=p["claim_map"].get(claimed,claimed)
                        if cid not in p["claim_ids"]:continue
                        objection=Objection("o"+str(len(self.objections)+1),
                            p["id"],cid,reviewer,
                            require_string(raw_ob,"issue"),
                            require_string(raw_ob,"consequence"),
                            require_string(raw_ob,"suggested_check"))
                        self.objections.append(objection)
                        self.events.record("revision_review_objection",
                            objection=asdict(objection))
                except (ValueError,OutputError):
                    self.warnings.append("Revision review invalid for "+p["id"])
            else:
                self.warnings.append("Independent revision recheck unavailable for "+p["id"])
        for claim in list(self.ledger.claims.values())[:self.max_claims]:
            if self.budget.debate_remaining()<1:break
            await self._translate_and_check(claim)
        # Adaptive seeds are permitted only after verification characteristics are known.
        # No extra seed is spent if no claim has a checkable verification result.
        if self.adaptive_seeds and self.verified and self.budget.debate_remaining()>10:
            for p in proposals:
                if self.budget.debate_remaining()<8:break
                sample=await self._call(p["family"],"proposal",{
                    "question":question,"requirements":req.as_data(),
                    "strategy":self.solver_strategies[p["family"]],
                    "independent":True,"source_spans_required":True})
                if sample:
                    p["stability"]=("stable" if sample.get("approach")==p["approach"]
                                    else "unstable")
                    for cid in p["claim_ids"]:
                        self.ledger.claims[cid].needs_re_evaluation = (
                            p["stability"]=="unstable" and
                            self.ledger.claims[cid].status is not ClaimStatus.SUPPORTED)
                    self.events.record("adaptive_sample",proposal_id=p["id"],
                                       stability=p["stability"])
        elif self.verified:
            self.events.record("adaptive_seed_eligible",count=len(self.verified),
                               action="disabled_by_configuration")
        # Questions without specific requirements remain explicitly unassessed coverage.
        coverage=None
        if self.enable_coverage:
            coverage=await self._call(self.translator_family,"coverage",{
                "requirements":req.as_data(),
                "claims":[{"id":c.id,"statement":c.statement,
                           "source_span":c.source_span} for c in self.ledger.claims.values()]})
        if coverage:
            try:self.coverage=string_list(coverage,"missing_requirements")
            except OutputError:self.warnings.append("Coverage response malformed")
        if self.budget.debate_remaining()>1 and self.moderator.begin_next_round():
            open_claims=[self.ledger.claims[cid]
                         for cid in self.moderator.priority_order()
                         if self.ledger.claims[cid].status in
                         {ClaimStatus.PROPOSED,ClaimStatus.UNRESOLVED}]
            jobs = [(claim, hunter, self.moderator.current_round)
                    for claim in open_claims[:self.hunter_cap]
                    if (hunter := next((f for f in self.solvers
                                        if f != claim.owner_family), None))]
            await self._hunt_batch(jobs)
            for claim in open_claims[:self.hunter_cap]:
                if self.budget.debate_remaining() < 1:
                    break
                for critic in self.critics:
                    if critic in {claim.owner_family,self.judge_family,
                                  self.auditor_family} or self.budget.debate_remaining()<1:
                        continue
                    opinion=await self._call(critic,"review",{
                        "claims":[{"id":claim.id,"statement":claim.statement}],
                        "proposal":{"id":claim.id,"approach":claim.statement}})
                    if opinion:
                        self.events.record("optional_critic",claim_id=claim.id,
                                           family=critic,opinion=opinion)
            # No new verifier evidence => do not start further debate rounds.
        # P4: at most one repair attempt for each remaining challenged claim.
        # The rewritten claim loses its old evidence and requires fresh anchoring.
        for c in list(self.ledger.claims.values())[:self.hunter_cap]:
            if not self.enable_repairs or self.budget.debate_remaining()<=3:break
            if c.status is not ClaimStatus.UNRESOLVED:continue
            repairer=next((f for f in ("nemotron","command","gpt-oss")
                           if f!=c.owner_family),None)
            if not repairer:continue
            suggestion=await self._call(repairer,"repair",{
                "claim_id":c.id,"claim":c.statement,"assumptions":c.assumptions,
                "obligations":self.extra_obligations})
            if not suggestion or not isinstance(suggestion.get("revised_statement"),str):
                continue
            new_text=suggestion["revised_statement"].strip()
            if not new_text or new_text==c.statement:continue
            closed_cause = self.moderator.bus.stalemates().get(c.id)
            if closed_cause in {"no_evidence_possible", "agents_gave_up"}:
                if not self.moderator.authorize_repair_from_stalemate(c.id,repairer):
                    continue
            else:
                try:
                    self.moderator.submit(Message("repair:"+c.id,c.id,Act.REPAIR,
                                                 repairer,repairer,new_text[:2400]))
                except (EvidenceRejected,MessageCap):
                    continue
            # Repair is a NEW proposal linked to its challenged predecessor,
            # not a retroactive modification that erases the disputed statement.
            new_id=c.id+":repair"
            if new_id in self.ledger.claims:
                continue
            anchored=validate_anchor(new_text,new_text,new_text,
                 assumptions=string_list(suggestion,"assumptions"))
            repair_claim=Claim(new_id,1,new_text,repairer,
                 source_span=anchored.source_span,
                 assumptions=list(anchored.assumptions),
                 quantifiers=list(anchored.quantifiers))
            self.ledger.add_claim(repair_claim)
            if c.quantifiers and set(c.quantifiers)!=set(repair_claim.quantifiers):
                self.warnings.append(new_id+": repair changed quantifiers; it is a different conjecture")
            self.events.record("repair_claim_proposed",replaces=c.id,
                 claim_id=new_id,source_family=repairer,source_span=new_text,
                 version=1)
            if self.budget.debate_remaining()>3:
                # P4 returns the new claim to P2 and one P3 review, as the
                # original proposal requires. Nothing becomes trusted by fiat.
                await self._translate_and_check(repair_claim)
                reviewer=next((f for f in self.solvers if f!=repairer),None)
                if reviewer and self.budget.debate_remaining()>3:
                    await self._hunt(repair_claim,reviewer,self.moderator.current_round)
            if repair_claim.status is not ClaimStatus.SUPPORTED:
                self.extra_obligations.append(new_id+": verify repaired meaning independently")
        # A repair may produce genuinely new verifier evidence. Only then may
        # a subsequent challenge round open. This is not another free-form
        # debate: Moderator.begin_next_round() enforces evidence gating.
        if (self.hunter_cap > 0 and self.budget.debate_remaining() > 2
                and self.moderator.begin_next_round()):
            self.events.record("evidence_gated_followup_round",
                               round=self.moderator.current_round)
            remaining = [self.ledger.claims[cid]
                         for cid in self.moderator.priority_order()
                         if self.ledger.claims[cid].status in
                         {ClaimStatus.PROPOSED, ClaimStatus.UNRESOLVED}]
            jobs = [(claim, hunter, self.moderator.current_round)
                    for claim in remaining[:self.hunter_cap]
                    if (hunter := next((f for f in self.solvers
                                        if f != claim.owner_family), None))]
            await self._hunt_batch(jobs)
        brief=ResearchResult(research_question=question,
                             completion_status="partial")
        brief.hypotheses=list(dict.fromkeys(h for p in proposals for h in p["hypotheses"]))
        brief.proposed_experiments=list(dict.fromkeys(x for p in proposals for x in p["experiments"]))
        brief.supported_findings=[c.statement for c in self.ledger.claims.values()
                                  if c.status is ClaimStatus.SUPPORTED]
        brief.checked_source_ids=sorted(self.checked_sources)
        brief.proposed_approach=" | ".join(p["approach"] for p in proposals)
        open_claims=[c for c in self.ledger.claims.values()
                     if c.status in {ClaimStatus.PROPOSED,ClaimStatus.UNRESOLVED}]
        brief.proof_obligations=list(dict.fromkeys(
            self.extra_obligations+
            [c.id+": "+c.statement+" (not independently established)"
             for c in open_claims]))
        # Unverified claims are obligations, not actual reviewer objections.
        brief.unresolved_objections=list(dict.fromkeys(
            self.coverage+
            [o.id+": "+o.issue+" (not yet independently resolved)"
             for o in self.objections]))
        if brief.proof_obligations:
            brief.next_actions.append(
                "Check the listed claims against independent evidence before "
                "treating this proposal as a verified result")
        if any(c.source_span is None for c in open_claims):
            brief.next_actions.append(
                "Supply verbatim claim quotations from the original proposal")
        # Judge input is blind to authors, family IDs and raw model transcripts.
        try: ledger_view=blind_ledger(self.ledger)
        except ValueError:
            ledger_view="Ledger exceeds model context; deterministic partial required"
            self.warnings.append("Ledger too long for blind judge")
        judge_payload={"ledger":ledger_view,
            "question_requirements":req.as_data(),
            "argument_map":[{"claim_id":x["claim_id"],"evidence_id":x["evidence_id"]}
                            for x in self.verified]}
        candidate=await self._call(self.judge_family,"judge",judge_payload,synthesis=True)
        if candidate is None and self.budget.remaining()>3:
            candidate=await self._call(self.judge_family,"judge",
                dict(judge_payload,retry_seed=1),synthesis=True)
        verdict=enforce_verdict(candidate or {"status":"unresolved",
            "partial_answer":brief.proposed_approach,"cause":"judge_error"},
            self.ledger)
        if isinstance(verdict.get("partial_answer"),str):
            brief.proposed_approach=verdict["partial_answer"]
        composition=compose_answer(
            str(verdict.get("answer") or verdict.get("partial_answer") or ""),
            [c.id for c in self.ledger.claims.values()], self.ledger)
        if composition.blocking:
            brief.limitations.append(
                "Final prose contains assertions without independent verification")
            assembled=Claim("composition:1",1,
                "Assembled answer has claims without independently scoped verification",
                "coordinator",status=ClaimStatus.UNRESOLVED)
            self.ledger.add_claim(assembled)
            self.events.record("composition_failed",claim_id=assembled.id,
                               blocking=list(composition.blocking),rung="prose")
            verdict=enforce_verdict(dict(verdict,status="unresolved",
                cause="composition_failure"),self.ledger)
            verdict["cause"]="composition_failure"
        # Keep all judge blockers visible, but do not relabel them as
        # objections raised by a reviewer. The blocking IDs are in verdict.
        brief.proof_obligations=list(dict.fromkeys(
            brief.proof_obligations+
            [cid+": independent verification required"
             for cid in verdict["blocking"]
             if not any(item.startswith(cid+":") for item in brief.proof_obligations)]))
        audit=None
        if mode!="quick" and self.auditor_family is not None:
            audit=await self._call(self.auditor_family,"audit",{"question":question,
                "requirements":req.as_data(),"blind_verdict":verdict,
                "research_result":brief.to_dict()},synthesis=True)
        if audit:
            try:
                brief.unresolved_objections=list(dict.fromkeys(
                     brief.unresolved_objections+string_list(audit,"issues")))
                brief.proposed_experiments=list(dict.fromkeys(
                     brief.proposed_experiments+string_list(audit,"suggested_checks")))
            except OutputError:self.warnings.append("Audit output malformed")
        elif mode!="quick":
            brief.limitations.append(
                "Independent auditor not assigned" if self.auditor_family is None
                else "Independent auditor unavailable")
        brief.completion_status=("partial" if proposals else "unresolved")
        brief.limitations=list(dict.fromkeys(brief.limitations+self.warnings))
        result={"research_result":brief.to_dict(),"proposals":proposals,
            "objections":[asdict(o) for o in self.objections],
            "author_responses":[asdict(a) for a in self.author_responses],
            "claims":[asdict(c) for c in self.ledger.claims.values()],
            "evidence":[asdict(e) for e in self.ledger.evidence.values()],
            "verdict":verdict,"composition":asdict(composition),
            "requirements":req.as_data(),"actual_models":self.actual_models,
            "duplicate_suggestions":self.duplicate_suggestions,
            "stalemates":self.moderator.bus.stalemates(),
            "warnings":self.warnings}
        if hasattr(self.events,"db") and hasattr(self.events,"run_id"):
            SQLiteLedger(self.events.db).save(self.events.run_id,self.ledger)
        self.events.record("run_finished",result=result)
        return result

class QuickCouncilRunner(FullCouncilRunner):
    """One independent solver, scoped checks, blind judge and composition.

    No debate, repair, coverage or audit calls. A research sketch may still
    return unresolved; confidence must come from evidence rather than votes.
    """
    def __init__(self,transport,events,budget,*,requirements=None,
                 solver="gpt-oss", translator_family=TRANSLATOR,
                 judge_family=JUDGE, solver_strategies=None):
        super().__init__(transport,events,budget,requirements=requirements,
                         solvers=(solver,),translator_family=translator_family,
                         judge_family=judge_family,
                         solver_strategies=solver_strategies,
                         max_claims=4,hunter_cap=0,
                         enable_coverage=False,enable_relevance=False,
                         critics=(),adaptive_seeds=False,enable_repairs=False)

    async def run(self,question:str,*,mode:str="quick"):
        return await super().run(question,mode="quick")

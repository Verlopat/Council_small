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
from council.bus import MessageCap
from council.evidence import EvidenceRejected
from council.extract import validate_anchor
from council.judge import blind_ledger, enforce_verdict, judge_failure
from council.models import Claim, ClaimStatus, Evidence, EvidenceKind, ResearchResult
from council.moderator import Moderator
from council.protocol import Message, Act
from council.parse import item_list, string_list, require_string, OutputError
from council.translate import plan
from council.verify.ladder import verify
from council.compose import compose_prose
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
                 solvers=FULL_SOLVERS,max_claims=12,hunter_cap=4):
        super().__init__(transport,events,budget,solvers=tuple(solvers))
        self.assignment=Assignment(tuple(solvers),translator=TRANSLATOR,
                                   judge=JUDGE,auditor=AUDITOR)
        self.requirements=requirements
        self.moderator=Moderator(self.ledger,events=events.record)
        self.max_claims=max_claims
        self.hunter_cap=hunter_cap
        self.coverage=[]
        self.verified=[]
        self.extra_obligations=[]

    def _anchors(self,p:dict,body:dict)->None:
        answer=body.get("answer") or p["approach"]
        if not isinstance(answer,str):answer=p["approach"]
        for raw,cid in zip(item_list(body,"claims"),p["claim_ids"]):
            claim=self.ledger.claims[cid]
            span=raw.get("source_span") or raw.get("span")
            if not isinstance(span,str):
                span=claim.statement if claim.statement in answer else ""
            if not span:continue
            try:
                anchored=validate_anchor(answer,claim.statement,span,
                      assumptions=string_list(raw,"assumptions"))
            except ValueError:
                self.warnings.append("Unanchored or quantifier-changing claim: "+cid)
                continue
            claim.source_span=anchored.source_span
            claim.assumptions=list(anchored.assumptions)
            claim.quantifiers=list(anchored.quantifiers)

    async def _translate_and_check(self,claim:Claim):
        if not claim.source_span:
            self.extra_obligations.append("Add an exact source span for "+claim.id)
            return
        if self.budget.debate_remaining()<=1:return
        proposal=await self._call(TRANSLATOR,"translate",{
            "claim_id":claim.id,"claim_version":claim.version,
            "statement":claim.statement,"source_span":claim.source_span,
            "assumptions":claim.assumptions,
            "rule":"A check must match the meaning of the claim"})
        if not proposal:return
        kind=proposal.get("claim_kind")
        scope=proposal.get("scope")
        artifact=proposal.get("artifact") or {}
        if not isinstance(kind,str) or not isinstance(scope,str) or not isinstance(artifact,dict):
            self.warnings.append("Malformed translator response for "+claim.id)
            return
        try:
            check_plan=plan(claim.id,claim.version,kind,scope=scope,
                            assumptions=tuple(claim.assumptions))
            result=await asyncio.to_thread(verify,check_plan,artifact)
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
        # A passing equation/source quote is NOT a security theorem proof.
        evidence_kind=(EvidenceKind.SOURCE if result.kind=="quote_exists"
                       else EvidenceKind.TEST)
        independent=(result.kind=="arithmetic" and
                     self._literal_arithmetic_alignment(claim.statement,artifact))
        if evidence_kind is EvidenceKind.SOURCE:
            independent=False
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

    async def _hunt(self,claim:Claim,hunter_family:str,round_number:int):
        if hunter_family==claim.owner_family or hunter_family==JUDGE:return
        result=await self._call(hunter_family,"hunter",{
            "claim":claim.statement,"assumptions":claim.assumptions,
            "scope":claim.scope,"claim_id":claim.id})
        if not result:return
        if not result.get("found"):return
        detail=result.get("counterexample")
        if not isinstance(detail,str) or not detail.strip():return
        message=Message("h"+str(len(self.moderator.bus.threads)+1)+":"+claim.id,
                        claim.id,Act.CHALLENGE,hunter_family,hunter_family,
                        detail[:2400],step_ref=detail[:300],round=round_number)
        try:
            self.moderator.submit(message)
            self.events.record("hunter_objection",claim_id=claim.id,
                               hunter_family=hunter_family,issue=detail)
        except (EvidenceRejected,MessageCap):
            self.warnings.append("Hunter cap or evidence policy rejected "+claim.id)

    async def run(self,question:str,*,mode:str="full")->dict:
        if not isinstance(question,str) or not question.strip():
            raise ValueError("Question required")
        req=self.requirements or Requirements(question)
        self.events.record("run_started",question=question,mode="full",
            requirements=req.as_data(),role_assignment=asdict(self.assignment),
            deadline_remaining=self.budget.remaining())
        proposals=[]
        raw=await asyncio.gather(*[
            self._call(family,"proposal",{
                "question":question,"requirements":req.as_data(),
                "independent":True,"source_spans_required":True})
            for family in self.solvers])
        for index,(family,body) in enumerate(zip(self.solvers,raw),1):
            if body is None:continue
            try:
                p=self._proposal(family,body,index)
                self._anchors(p,body)
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
            self.events.record("run_finished",result=result)
            return result
        for i,p in enumerate(proposals):
            if self.budget.debate_remaining()<1:break
            peer=proposals[(i+1)%len(proposals)]["family"] if len(proposals)>1 else None
            if peer and peer!=p["family"]:
                await self._extract_rival(p,peer)
        for claim in list(self.ledger.claims.values())[:self.max_claims]:
            if self.budget.debate_remaining()<1:break
            await self._translate_and_check(claim)
        # Adaptive seeds are permitted only after verification characteristics are known.
        # No extra seed is spent if no claim has a checkable verification result.
        if self.verified and self.budget.debate_remaining()>10:
            self.events.record("adaptive_seed_eligible",count=len(self.verified),
                               action="deferred_until_calibrated")
        # Questions without specific requirements remain explicitly unassessed coverage.
        coverage=await self._call(TRANSLATOR,"coverage",{
            "requirements":req.as_data(),
            "claims":[{"id":c.id,"statement":c.statement,
                       "source_span":c.source_span} for c in self.ledger.claims.values()]})
        if coverage:
            try:self.coverage=string_list(coverage,"missing_requirements")
            except OutputError:self.warnings.append("Coverage response malformed")
        if self.budget.debate_remaining()>1 and self.moderator.begin_next_round():
            open_claims=[c for c in self.ledger.claims.values()
                         if c.status in {ClaimStatus.PROPOSED,ClaimStatus.UNRESOLVED}]
            for claim in open_claims[:self.hunter_cap]:
                if self.budget.debate_remaining()<1:break
                hunter=next((f for f in self.solvers if f!=claim.owner_family),None)
                if hunter:
                    await self._hunt(claim,hunter,self.moderator.current_round)
            # No new verifier evidence => do not start further debate rounds.
        brief=ResearchResult(research_question=question,
                             completion_status="partial")
        brief.hypotheses=list(dict.fromkeys(h for p in proposals for h in p["hypotheses"]))
        brief.proposed_experiments=list(dict.fromkeys(x for p in proposals for x in p["experiments"]))
        brief.supported_findings=[c.statement for c in self.ledger.claims.values()
                                  if c.status is ClaimStatus.SUPPORTED]
        brief.checked_source_ids=[]
        brief.proposed_approach=" | ".join(p["approach"] for p in proposals)
        brief.proof_obligations=list(dict.fromkeys(self.extra_obligations))
        brief.unresolved_objections=list(dict.fromkeys(self.coverage+
            [c.id+": "+c.statement for c in self.ledger.claims.values()
             if c.status in {ClaimStatus.PROPOSED,ClaimStatus.UNRESOLVED}]))
        # Judge input is blind to authors, family IDs and raw model transcripts.
        try: ledger_view=blind_ledger(self.ledger)
        except ValueError:
            ledger_view="Ledger exceeds model context; deterministic partial required"
            self.warnings.append("Ledger too long for blind judge")
        candidate=await self._call(JUDGE,"judge",{
            "ledger":ledger_view,
            "question_requirements":req.as_data(),
            "argument_map":[{"claim_id":x["claim_id"],"evidence_id":x["evidence_id"]}
                            for x in self.verified]},synthesis=True)
        verdict=enforce_verdict(candidate or {"status":"unresolved",
            "partial_answer":brief.proposed_approach,"cause":"judge_error"},
            self.ledger)
        if isinstance(verdict.get("partial_answer"),str):
            brief.proposed_approach=verdict["partial_answer"]
        composition=compose_prose([c.id for c in self.ledger.claims.values()],self.ledger)
        if composition.blocking:
            brief.limitations.append("Composition contains unverified claims")
        brief.unresolved_objections=list(dict.fromkeys(brief.unresolved_objections+
                            list(verdict["blocking"])))
        audit=await self._call(AUDITOR,"audit",{"question":question,
            "requirements":req.as_data(),"blind_verdict":verdict,
            "research_result":brief.to_dict()},synthesis=True)
        if audit:
            try:
                brief.unresolved_objections=list(dict.fromkeys(
                     brief.unresolved_objections+string_list(audit,"issues")))
                brief.proposed_experiments=list(dict.fromkeys(
                     brief.proposed_experiments+string_list(audit,"suggested_checks")))
            except OutputError:self.warnings.append("Audit output malformed")
        else: brief.limitations.append("Independent auditor unavailable")
        brief.completion_status=("partial" if proposals else "unresolved")
        brief.limitations=list(dict.fromkeys(brief.limitations+self.warnings))
        result={"research_result":brief.to_dict(),"proposals":proposals,
            "claims":[asdict(c) for c in self.ledger.claims.values()],
            "evidence":[asdict(e) for e in self.ledger.evidence.values()],
            "verdict":verdict,"composition":asdict(composition),
            "requirements":req.as_data(),"actual_models":self.actual_models,
            "warnings":self.warnings}
        self.events.record("run_finished",result=result)
        return result

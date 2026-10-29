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
from council.ledger import SQLiteLedger
from council.models import Claim, ClaimStatus, Evidence, EvidenceKind, ResearchResult, Objection, AuthorResponse
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
                 solvers=FULL_SOLVERS,max_claims=12,hunter_cap=4,
                 translator_family=TRANSLATOR,judge_family=JUDGE,
                 auditor_family=AUDITOR,enable_coverage=True,
                 enable_relevance=False,critics=(),adaptive_seeds=False,
                 enable_repairs=True):
        super().__init__(transport,events,budget,solvers=tuple(solvers))
        self.assignment=Assignment(tuple(solvers),translator=translator_family,
                                   judge=judge_family,auditor=auditor_family)
        self.translator_family=translator_family
        self.judge_family=judge_family
        self.auditor_family=auditor_family
        self.requirements=requirements
        self.moderator=Moderator(self.ledger,events=events.record)
        self.max_claims=max_claims
        self.hunter_cap=hunter_cap
        self.coverage=[]
        self.verified=[]
        self.enable_coverage=bool(enable_coverage)
        self.enable_relevance=bool(enable_relevance)
        self.critics=tuple(critics)
        self.adaptive_seeds=bool(adaptive_seeds)
        self.enable_repairs=bool(enable_repairs)
        self.extra_obligations=[]
        self.objections=[]
        self.author_responses=[]

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
        proposal=await self._call(self.translator_family,"translate",{
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

    async def _hunt(self,claim:Claim,hunter_family:str,round_number:int):
        if hunter_family==claim.owner_family or hunter_family==self.judge_family:return
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
        self.events.record("run_started",question=question,mode=mode,
            pipeline="evidence",
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
            if hasattr(self.events,"db") and hasattr(self.events,"run_id"):
                SQLiteLedger(self.events.db).save(self.events.run_id,self.ledger)
            self.events.record("run_finished",result=result)
            return result
        for i,p in enumerate(proposals):
            if self.budget.debate_remaining()<1:break
            peer=proposals[(i+1)%len(proposals)]["family"] if len(proposals)>1 else None
            if peer and peer!=p["family"]:
                await self._extract_rival(p,peer)
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
            for claim in open_claims[:self.hunter_cap]:
                if self.budget.debate_remaining()<1:break
                hunter=next((f for f in self.solvers if f!=claim.owner_family),None)
                if hunter:
                    await self._hunt(claim,hunter,self.moderator.current_round)
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
            [o.id+": "+o.issue+" (not yet independently resolved)" for o in self.objections]+
            [c.id+": "+c.statement for c in self.ledger.claims.values()
             if c.status in {ClaimStatus.PROPOSED,ClaimStatus.UNRESOLVED}]))
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
        composition=compose_prose([c.id for c in self.ledger.claims.values()],self.ledger)
        if composition.blocking:
            brief.limitations.append("Composition contains unverified claims")
            assembled=Claim("composition:1",1,
                "Assembled answer has claims without independently scoped verification",
                "coordinator",status=ClaimStatus.UNRESOLVED)
            self.ledger.add_claim(assembled)
            self.events.record("composition_failed",claim_id=assembled.id,
                               blocking=list(composition.blocking),rung="prose")
            verdict=enforce_verdict(dict(verdict,status="unresolved",
                cause="composition_failure"),self.ledger)
            verdict["cause"]="composition_failure"
        brief.unresolved_objections=list(dict.fromkeys(brief.unresolved_objections+
                            list(verdict["blocking"])))
        audit=None
        if mode!="quick":
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
        elif mode!="quick": brief.limitations.append("Independent auditor unavailable")
        brief.completion_status=("partial" if proposals else "unresolved")
        brief.limitations=list(dict.fromkeys(brief.limitations+self.warnings))
        result={"research_result":brief.to_dict(),"proposals":proposals,
            "objections":[asdict(o) for o in self.objections],
            "author_responses":[asdict(a) for a in self.author_responses],
            "claims":[asdict(c) for c in self.ledger.claims.values()],
            "evidence":[asdict(e) for e in self.ledger.evidence.values()],
            "verdict":verdict,"composition":asdict(composition),
            "requirements":req.as_data(),"actual_models":self.actual_models,
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
    def __init__(self,transport,events,budget,*,requirements=None):
        super().__init__(transport,events,budget,requirements=requirements,
                         solvers=("gpt-oss",),max_claims=4,hunter_cap=0,
                         enable_coverage=False,enable_relevance=False,
                         critics=(),adaptive_seeds=False,enable_repairs=False)

    async def run(self,question:str,*,mode:str="quick"):
        return await super().run(question,mode="quick")

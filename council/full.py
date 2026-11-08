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
import os
import re
from types import SimpleNamespace

from council.assignment import Assignment
from council.dependencies import Dependency
from council.bus import MessageCap, MessageBus
from council.evidence import EvidenceRejected
from council.extract import (validate_anchor, locate_source_span, numbered_sentence_excerpt,
                             source_sentence_ids, suggest_duplicate_claims)
from council.judge import (blind_ledger, enforce_verdict, judge_failure,
                           topic_of, TOPIC_SECTIONS, normalize_topic_judgment, _flat)
from council.claim_filter import is_meta_claim, close_to_owner
from council.ledger import SQLiteLedger
from council.models import Claim, ClaimStatus, Evidence, EvidenceKind, ResearchResult, Objection, AuthorResponse
from council.obligations import group_by_claim_id
from council.moderator import Moderator
from council.protocol import Message, Act
from council.parse import item_list, string_list, require_string, OutputError
from council.translate import plan, decisive_if_supported
from council.verify.ladder import verify
from council.compose import compose_answer
from council.workflow import CouncilRunner
from council.requirements import Requirements
from council.vrf_sanity import scan_vrf_games
from council.vrf_audit import (scan_audit_issues, objection_conflicts,
                               objection_scope_noise)
from council.objection_sections import presentation_sections
from council.definition_sources import (classify as definition_kind, consult as consult_definition,
                                        game_step, is_vrf_definition_question,
                                        SECTION_HEADINGS, is_summary, topic_text)

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
        self.reference_checks=[]
        self._definition_context_by_claim={}
        self._translator_unavailable=False
        self.objections=[]
        self.grounded_objection_verdicts={}
        self.author_responses=[]

    def _anchors(self,p:dict,body:dict)->None:
        # Only text authored in this proposal can establish provenance. A
        # statement appearing later in the blind judge answer is not an anchor.
        sources=[("approach",p["approach"])]
        answer=body.get("answer")
        if isinstance(answer,str) and answer and answer!=p["approach"]:
            sources.append(("answer",answer))
        # Track which original [S#] sentences are cited by *owner* claims.
        # Their source-level coverage can suppress later verbatim rival copies.
        # It does not establish claim equivalence or scientific correctness.
        tagged=list(re.finditer(r"(?<!\S)\[S([1-9][0-9]*)\]\s+",p["approach"]))
        section_by_sentence={}
        current_scope=None
        group_section={"1_full_uniqueness":"3.1",
                       "2_trusted_uniqueness":"3.3",
                       "3_pseudorandomness":"3.4"}
        for j,tag in enumerate(tagged):
            stop=tagged[j+1].start() if j+1<len(tagged) else len(p["approach"])
            key=topic_of(p["approach"][tag.end():stop])
            if key in group_section:
                current_scope=group_section[key]
            section_by_sentence[int(tag.group(1))]=current_scope
        p["claim_sentence_ids"]={}
        for raw,cid in zip(item_list(body,"claims"),p["claim_ids"]):
            claim=self.ledger.claims[cid]
            declared=raw.get("sentence_ids")
            ids=([i for i in declared if type(i) is int and 1<=i<=100]
                 if isinstance(declared,list) else [])
            if not ids and isinstance(raw.get("source_span"),str):
                ids=source_sentence_ids(p["approach"],raw["source_span"])
            ids=[i for i in ids if i in section_by_sentence]
            # Model-supplied [S#] IDs can refer to a completely different
            # game when [S1]...[S5] share a physical line. Check the topic of
            # the actual cited segment *before* trusting its provenance.
            wanted=topic_of(claim.statement)
            cited=numbered_sentence_excerpt(p["approach"],ids) if ids else None
            cited_sections={section_by_sentence[i] for i in ids
                            if section_by_sentence.get(i)}
            if (cited and wanted in group_section and
                    (cited_sections and cited_sections!={group_section[wanted]}
                     or topic_of(cited) in group_section
                     and topic_of(cited)!=wanted)):
                self.events.record("anchor_topic_mismatch",
                    claim_id=cid,cited_ids=ids,
                    cited_topic=topic_of(cited),
                    inherited_sections=sorted(cited_sections),
                    claim_topic=wanted)
                ids=[]
            if not ids and isinstance(raw.get("source_span"),str):
                possible=source_sentence_ids(p["approach"],raw["source_span"])
                excerpt=numbered_sentence_excerpt(p["approach"],possible)
                recovered_sections={section_by_sentence[i] for i in possible
                                    if section_by_sentence.get(i)}
                if (possible and excerpt and
                        (wanted not in group_section or
                         (not recovered_sections or
                          recovered_sections=={group_section[wanted]})
                         and topic_of(excerpt) in {wanted,"5_other"})):
                    ids=possible
            p["claim_sentence_ids"][cid]=ids
            scopes={section_by_sentence[i] for i in ids
                    if section_by_sentence[i] is not None}
            if len(scopes)==1:
                section=next(iter(scopes))
                self._definition_context_by_claim[cid]=(
                    SECTION_HEADINGS[section],section)
            declared_span=raw.get("source_span") or raw.get("span")
            assumptions=string_list(raw,"assumptions")
            anchored=None
            reason="no_exact_source_span"
            recovered=False
            for source_name,source_text in sources:
                candidates=[]
                if isinstance(declared_span,str) and declared_span.strip():
                    # A verbatim quote can still cite the WRONG security game.
                    quoted_topic=topic_of(declared_span)
                    if (wanted not in group_section or
                            quoted_topic not in group_section or
                            quoted_topic==wanted):
                        candidates.append(declared_span)
                    else:
                        self.events.record("anchor_quote_topic_mismatch",
                            claim_id=cid,claim_topic=wanted,
                            cited_topic=quoted_topic)
                # The only auto-repair is a *verbatim* statement already in
                # the original response. Never infer paraphrase equivalence.
                if (locate_source_span(source_text, claim.statement) is not None
                        and claim.statement not in candidates):
                    candidates.append(claim.statement)
                for candidate in candidates:
                    # Even a verbatim quote of an unlabeled sentence can be
                    # from a different game. [S#] inherits the last named
                    # topic in the author's approach (e.g. S3 after S1).
                    if source_name=="approach" and wanted in group_section:
                        quote_ids=source_sentence_ids(p["approach"],candidate)
                        quote_sections={section_by_sentence[i] for i in quote_ids
                                        if section_by_sentence.get(i)}
                        if (quote_sections and
                                quote_sections!={group_section[wanted]}):
                            self.events.record("anchor_quote_topic_mismatch",
                                claim_id=cid,claim_topic=wanted,
                                quoted_sections=sorted(quote_sections))
                            continue
                    try:
                        anchored=validate_anchor(
                            source_text,claim.statement,candidate,
                            assumptions=assumptions)
                        recovered=(candidate!=declared_span
                                   or candidate!=anchored.source_span)
                        break
                    except ValueError as exc:
                        reason=("quantifier_or_modality_mismatch"
                                if "Quantifier or modality" in str(exc)
                                else "source_span_not_located")
                if anchored is not None:
                    if recovered or source_name!="approach":
                        self.events.record("claim_anchor_recovered",claim_id=cid,
                            method="verbatim_statement_or_original_answer",
                            source_field=source_name)
                    break
            if anchored is None:
                # Sentence IDs identify original source text deterministically.
                # They DO NOT establish equivalence with the model's claim.
                # Therefore the claim remains blocked for semantic alignment,
                # and non-definition verification cannot certify it.
                original=numbered_sentence_excerpt(p["approach"],ids) if ids else None
                if original:
                    claim.source_span=original
                    claim.assumptions=assumptions
                    claim.needs_re_evaluation=True
                    self.events.record("claim_sentence_provenance",claim_id=cid,
                        sentence_ids=ids,semantic_alignment="unchecked")
                    self.extra_obligations.append(cid+
                        ": numbered source sentences located; claimed meaning "
                        "requires independent alignment review")
                    continue
                self.warnings.append(cid+": source anchoring failed ("+reason+")")
                self.events.record("claim_anchor_rejected",claim_id=cid,
                                   reason=reason)
                self.extra_obligations.append(
                    cid+": provide an exact quote from the original proposal")
                continue
            claim.source_span=anchored.source_span
            claim.assumptions=list(anchored.assumptions)
            claim.quantifiers=list(anchored.quantifiers)
            # A substring can establish quotation provenance without
            # establishing the meaning of the model's rewritten claim.
            # Never promote this into support if the claim is not itself
            # contained verbatim (allowing only formatting equivalence).
            if locate_source_span(anchored.source_span,claim.statement) is None:
                claim.needs_re_evaluation=True
                self.events.record("claim_semantic_alignment_unchecked",
                                   claim_id=cid,source="quoted_span")
                self.extra_obligations.append(
                    cid+": quotation located, but the claim's rewritten "
                    "meaning requires independent semantic alignment")

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
        if is_meta_claim(claim.statement):
            self.events.record("meta_claim_verification_skipped",claim_id=claim.id)
            self.extra_obligations.append(
                claim.id+": statement is about the answer, not the research question")
            return
        if is_summary(claim.statement):
            self.events.record("redundant_summary_skipped",claim_id=claim.id)
            self.extra_obligations.append(
                claim.id+": redundant summary; evaluate its underlying claims")
            return
        question=(self.requirements.objective
                  if self.requirements else self._current_question)
        if is_vrf_definition_question(question):
            # Game definitions are text-reference comparisons. A translator
            # cannot mechanically verify them, and repeatedly calling GLM
            # for repairs wastes the free-tier budget.
            definition=definition_kind(question,claim.statement)
            if definition is not None:
                heading,section=definition
                check=consult_definition(self.paper_index,heading,section,claim.id)
                self.reference_checks.append(check)
                self.events.record("definition_reference_checked",**check)
                self.extra_obligations.append(
                    claim.id+": RFC 9381 §"+section+
                    " reference provenance located; semantic alignment "
                    "remains advisory and unverified")
            elif re.search(r"\breduc\w*\b|\b(?:lwe|sis)\b|"
                           r"\b(?:conjectur\w*|theorem|hardness)\b",
                           claim.statement,re.I):
                self.extra_obligations.append(
                    claim.id+": scheme-specific reduction/security assertion "
                    "not validated by a game definition; separate proof needed")
            else:
                self.extra_obligations.append(
                    claim.id+": game-step definition/source alignment needs RFC review")
            self.events.record("translator_skipped",claim_id=claim.id,
                               reason="definitional_question")
            return
        definition=definition_kind(question,claim.statement)
        if definition is None and game_step(question,claim.statement):
            definition=self._definition_context_by_claim.get(claim.id)
            if definition is None:
                # The step belongs to a VRF security-game description, but
                # no trusted section label can be determined from the claim.
                # Avoid spending GLM quota OR mislabeling it as RFC §3.1.
                self.events.record("definition_game_step_unscoped",
                                   claim_id=claim.id)
                self.extra_obligations.append(
                    claim.id+": VRF game-step definition lacks a reliable "
                    "section label; RFC alignment must be checked manually")
                return
        if definition is not None:
            heading, section=definition
            result=consult_definition(self.paper_index,heading,section,claim.id)
            self.reference_checks.append(result)
            self.events.record("definition_reference_checked",**result)
            self.extra_obligations.append(claim.id+": RFC 9381 Section "+section+
                (" reference heading located; meaning remains unverified"
                 if result["heading_found"] else
                 " not indexed; index the official RFC for provenance"))
            return
        if claim.needs_re_evaluation:
            self.extra_obligations.append(
                claim.id+": sentence provenance exists but claim-to-source "
                "semantic alignment remains unchecked")
            return
        if self._translator_unavailable:
            self.extra_obligations.append(
                claim.id+": translator unavailable after earlier failures in this run")
            return
        if not claim.source_span:
            self.extra_obligations.append("Add an exact source span for "+claim.id)
            return
        if self.budget.debate_remaining()<=1:return
        proposal=await self._call(self.translator_family,"translate",{
            "claim_id":claim.id,"claim_version":claim.version,
            "statement":claim.statement,"source_span":claim.source_span,
            "assumptions":claim.assumptions,
            "rule":"A check must match the meaning of the claim"})
        if not proposal:
            # A failing role is not retried for each remaining claim in the
            # same run: the shared free-tier family has already exhausted its
            # eligible fallback endpoints or returned invalid output.
            self._translator_unavailable=True
            self.events.record("role_disabled_for_run",role="translate",
                               family=self.translator_family,
                               reason="initial translator failed")
            self.extra_obligations.append(
                claim.id+": translator unavailable; independent verification deferred")
            return
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

    def _missing_solver_actions(self,proposals:list[dict])->list[str]:
        present={p["family"] for p in proposals}
        actions=[]
        for family in self.solvers:
            if family in present:
                continue
            matched=[row for row in self.warnings
                     if row.startswith("proposal/"+family+":")]
            reason=matched[-1].split(": ",1)[1] if matched else "no valid proposal returned"
            if "unconfigured or free mode unconfirmed" in reason:
                actions.append("Confirm usable free API access and credentials for "+
                               family+" before attempting full mode")
            elif "plan_not_answer" in reason:
                actions.append(f"{family}: proposal only outlined tasks; "
                               "an actual answer is required")
            elif "invalid structured output" in reason:
                actions.append(f"{family}: structured proposal validation failed ("+
                               reason[:180]+")")
            else:
                actions.append(f"{family}: inference failed in this run ("+
                               reason[:200]+"); inspect provider health and quota")
        return actions

    def _vrf_findings(self,question:str,proposals:list[dict])->list[dict]:
        # Claims are primary. Only independently authored approach sentences
        # that no claim anchors are checked as separate advisory surfaces.
        claims=list(self.ledger.claims.values())
        findings=scan_vrf_games(question,claims)
        covered_kinds={(row["claim_id"].split(":")[0],row["kind"])
                       for row in findings}
        # A structured claim may paraphrase away an error present in its
        # anchored original sentence. Check its provenance as a second,
        # explicitly labeled advisory surface rather than silently declaring
        # the original source sentence covered.
        for c in claims:
            if not c.source_span or topic_text(c.source_span)==topic_text(c.statement):
                continue
            for item in scan_vrf_games(question,[SimpleNamespace(
                    id=c.id+":source",statement=c.source_span)]):
                label=(c.id.split(":")[0],item["kind"])
                if label not in covered_kinds:
                    findings.append(item)
                    covered_kinds.add(label)
        for p in proposals:
            approach=p["approach"]
            # [S1], [S2] and [S3] can share a physical line.
            parts=[
                (int(m.group(1)),m.group(2).strip())
                for m in re.finditer(
                    r"(?s)(?<!\S)\[S([0-9]+)\]\s+(.+?)"
                    r"(?=\s+\[S[0-9]+\]|\Z)", approach)]
            if not parts:
                parts=[(i,chunk.strip()) for i,chunk in enumerate(
                    re.split(r"(?<=[.!?])\s+",approach),1) if chunk.strip()]
            for number,content in parts:
                canonical=topic_text(content)
                covered=False
                for cid in p["claim_ids"]:
                    source=self.ledger.claims[cid].source_span
                    if source:
                        excerpt=topic_text(source)
                        if len(excerpt)>=24 and (excerpt in canonical or canonical in excerpt):
                            covered=True
                            break
                if covered:
                    continue
                extra=scan_vrf_games(question,[SimpleNamespace(
                    id=p["id"]+":approach:S"+str(number),statement=content)])
                for item in extra:
                    label=(p["id"],item["kind"])
                    if label not in covered_kinds:
                        findings.append(item)
                        covered_kinds.add(label)
        return findings

    async def _consolidate_topics(self, question: str, warnings: list[dict]) -> list[dict]:
        """Three bounded RFC-game comparisons; never upgrade evidence."""
        if not re.search(r"\bVRF\b|verifiable random function", question, re.I):
            return []
        warning_map={}
        for w in warnings:
            warning_map.setdefault(w["claim_id"].split(":source")[0],set()).add(w["kind"])
        out=[]
        for topic,(group,section) in TOPIC_SECTIONS.items():
            claims=[c for c in self.ledger.claims.values()
                    if topic_of(c.statement)==group and c.id.startswith("p")
                    and not getattr(c,"duplicate_of",None)]
            versions=[{"id":c.id,"statement":c.statement[:1000],
                       "flags":sorted(warning_map.get(c.id,set()))}
                      for c in claims[:18]]
            excerpt=None
            if self.paper_index is not None:
                try:
                    excerpt=self.paper_index.rfc_section_excerpt(section,max_chars=6000)
                except (AttributeError,ValueError):
                    pass
            candidate=None
            if (versions and excerpt and not excerpt.get("truncated")
                    and self.budget.debate_remaining()>8):
                candidate=await self._call(self.judge_family,"topic_judge",{
                    "topic":topic,"section":section,"reference":excerpt,
                    "versions":versions,
                    "task":"Compare every version to the exact source text; "
                           "choose the best source-aligned description. "
                           "Do not claim formal verification."}, synthesis=True)
            if candidate is not None:
                # The caller already knows these context fields. Gemini may
                # omit them while correctly returning version judgments.
                candidate.setdefault("topic",topic)
                candidate["summary"]=candidate.get("summary") or ""
            result=normalize_topic_judgment(topic,excerpt,versions,candidate)
            self.events.record("topic_consolidation",topic=topic,
                section=section,best_version_id=result["best_version_id"],
                reference_complete=result["reference_complete"],
                model_available=bool(candidate))
            out.append(result)
        return out

    @staticmethod
    def _cohere_proposal_references(refs: dict[str,dict]) -> dict[str,dict]:
        """Preserve short verbatim RFC excerpts for Cohere's proposal only.

        Explicitly mark shortened excerpts as partial. Full indexed sections
        remain available to judges and other families, so concise drafting
        input cannot be mistaken for complete citation evidence.
        """
        limits={"3.1":800,"3.3":800,"3.4":1200}
        reduced={}
        for section,limit in limits.items():
            source=refs.get(section)
            if not source:
                continue
            excerpt=str(source.get("excerpt",""))
            if not excerpt:
                continue
            if len(excerpt)<=limit:
                reduced[section]=dict(source)
                continue
            cut=excerpt.rfind("\n",0,limit)
            if cut<limit//2:
                cut=excerpt.rfind(" ",0,limit)
            if cut<limit//2:
                cut=limit
            reduced[section]=dict(source,excerpt=excerpt[:cut].rstrip(),
                                  truncated=True,
                                  excerpt_purpose="verbatim drafting context only; "
                                  "full RFC section remains in local index")
        return reduced

    async def _stop_for_independence(self, question: str, req: Requirements,
                                      proposals: list[dict]) -> dict:
        """Preserve a single useful answer without implying peer independence.

        With exactly one valid proposal, skip expensive peer review, hunter,
        repair and general synthesis, but do bounded RFC topic comparisons
        and optionally one independent audit. No evidence becomes verified.
        """
        self.events.record("run_stopped_early",
            reason="insufficient_independence",valid_solver_count=len(proposals),
            required_solver_count=2,
            reduced_assessment=bool(proposals))
        findings=self._vrf_findings(question,proposals)
        for c in self.ledger.claims.values():
            definition=definition_kind(question,c.statement)
            if definition is not None:
                heading,section=definition
                check=consult_definition(self.paper_index,heading,section,c.id)
                self.reference_checks.append(check)
                self.events.record("definition_reference_checked",**check)
        topics=[]
        audit=None
        audit_issues=[]
        audit_advisories=[]
        if proposals:
            topics=await self._consolidate_topics(question,findings)
            if (self.auditor_family is not None and
                    self.budget.debate_remaining()>6):
                # This audit is independent of the single proposer, but it
                # cannot replace missing independent *solver* proposals.
                audit=await self._call(self.auditor_family,"audit",{
                    "question":question,
                    "requirements":req.as_data(),
                    "single_proposal":True,
                    "research_result":{
                        "proposed_approach":proposals[0]["approach"],
                        "claims":[{"id":c.id,"statement":c.statement,
                                   "source_span":c.source_span}
                                  for c in self.ledger.claims.values()]},
                    "reference_sections":self._rfc_game_references(question)
                },synthesis=True)
            if audit:
                try:
                    audit_issues=string_list(audit,"issues")
                    audit_advisories=scan_audit_issues(question,audit_issues)
                except OutputError:
                    self.warnings.append("Single-proposal audit returned malformed issues")
        brief=ResearchResult(research_question=question,
                             completion_status=("partial_single_proposal"
                                                if proposals else "unresolved"))
        brief.proposed_approach="\n\n".join(
            "Proposal "+p["id"]+" ("+p["family"]+"):\n"+
            p["approach"] for p in proposals)
        brief.hypotheses=list(dict.fromkeys(h for p in proposals
                                          for h in p["hypotheses"]))
        brief.unresolved_objections=[
            "audit:"+str(i)+": "+issue+" (advisory; not independently verified)"
            for i,issue in enumerate(audit_issues,1)]
        brief.proof_obligations=group_by_claim_id(
            self.extra_obligations+
            [c.id+": "+c.statement+" (not independently established)"
             for c in self.ledger.claims.values()],self.ledger.claims)
        brief.limitations=[
            "Insufficient independent proposals: "+str(len(proposals))+
            "/"+str(len(self.solvers))+" configured solver families returned "
            "valid structured proposals",
            "Single-proposal RFC alignment is an advisory comparison, not "
            "independent solver consensus or cryptographic verification",
            "Cross-review, author revisions, hunter and full synthesis skipped "
            "to conserve free-tier quota"]
        if proposals and not audit:
            brief.limitations.append("Single-proposal independent auditor unavailable")
        brief.next_actions=self._missing_solver_actions(proposals)+[
            "Obtain at least two independent valid proposals for full peer review"]
        if findings:
            brief.limitations.append(
                "Advisory VRF game warnings found; not verified counterexamples")
        brief.limitations=list(dict.fromkeys(brief.limitations+self.warnings))
        blocking=sorted(self.ledger.claims)
        result={"research_result":brief.to_dict(),"proposals":proposals,
            "claims":[asdict(c) for c in self.ledger.claims.values()],
            "evidence":[asdict(e) for e in self.ledger.evidence.values()],
            "objections":[],"author_responses":[],
            "verdict":{"status":"unresolved","answer":None,"partial_answer":None,
                       "blocking":blocking,"basis":["Fewer than two independent valid proposals"],
                       "cause":"insufficient_independence"},
            "requirements":req.as_data(),"actual_models":self.actual_models,
            "advisory_findings":findings,"reference_checks":self.reference_checks,
            "topic_consolidation":topics,
            "audit_advisory_findings":audit_advisories,
            "single_proposal_audit_issues":audit_issues,
            "rfc_conflicting_objections":[],
            "objections_withheld_from_revision":[],
            "judge_source":"local_policy","role_coverage":{
                "requested_solvers":list(self.solvers),
                "valid_proposer_families":[p["family"] for p in proposals],
                "review_objection_count":0,
                "independent_audit_completed":bool(audit),
                "audit_family":self.auditor_family,
                "stop_reason":"insufficient_independence",
                "single_proposal_assessed":bool(proposals)},
            "warnings":self.warnings}
        if hasattr(self.events,"db") and hasattr(self.events,"run_id"):
            SQLiteLedger(self.events.db).save(self.events.run_id,self.ledger)
        self.events.record("single_proposal_assessment_completed",
            topic_results=len(topics),selected_games=sum(
                bool(row.get("best_version_id")) for row in topics),
            auditor_completed=bool(audit),
            independent_proposals=len(proposals))
        self.events.record("run_finished",result=result)
        return result

    def _rfc_game_references(self, question: str) -> dict[str,dict]:
        """Fetch only complete, officially indexed RFC 9381 game sections.

        The reference is common public context for every independent solver.
        Missing/truncated/untrusted text is never silently treated as the RFC.
        """
        if not re.search(r"\bVRF\b|verifiable random function",question,re.I):
            return {}
        refs={}
        if self.paper_index is None:
            return refs
        for section in ("3.1","3.3","3.4"):
            try:
                row=self.paper_index.rfc_section_excerpt(section,max_chars=10000)
            except (AttributeError,ValueError):
                row=None
            if (isinstance(row,dict) and row.get("excerpt")
                    and not row.get("truncated")
                    and row.get("section")==section
                    and row.get("document_id")=="rfc9381"
                    and row.get("source_uri")=="https://www.rfc-editor.org/rfc/rfc9381.txt"):
                refs[section]=row
        return refs

    def _reference_for_claims(self, claim_ids: list[str],
                              refs: dict[str,dict]) -> dict[str,dict]:
        sections=set()
        groups={"1_full_uniqueness":"3.1",
                "2_trusted_uniqueness":"3.3",
                "3_pseudorandomness":"3.4"}
        for cid in claim_ids:
            claim=self.ledger.claims.get(cid)
            if claim is None:
                continue
            topic=topic_of(claim.statement)
            section=groups.get(topic)
            if section is None:
                original=self._definition_context_by_claim.get(cid)
                section=original[1] if original else None
            if section and section in refs:
                sections.add(section)
        return {key:refs[key] for key in sorted(sections)}

    async def _ground_objections(self, rfc_refs: dict[str,dict],
                                 objections: list[Objection]) -> dict[str,dict]:
        """Up to three optional, quote-checked RFC objection judgments.

        An unavailable, omitted, or ungrounded model result is UNJUDGED,
        never automatically 'valid'. This is source-text advisory review,
        not mathematical verification.
        """
        mapping={"1_full_uniqueness":"3.1","2_trusted_uniqueness":"3.3",
                 "3_pseudorandomness":"3.4"}
        by_section={}
        for obj in objections:
            claim=self.ledger.claims.get(obj.claim_id)
            if claim is None:
                continue
            section=mapping.get(topic_of(claim.statement))
            if section in rfc_refs:
                by_section.setdefault(section,[]).append((obj,claim))
        outcomes={}
        for section in ("3.1","3.3","3.4"):
            candidates=by_section.get(section,[])[:8]
            if (not candidates or
                    not self.judge_family or
                    self.budget.debate_remaining()<=8):
                continue
            ref=rfc_refs[section]
            if ref.get("truncated") or not ref.get("excerpt"):
                continue
            response=await self._call(self.judge_family,"objection_judge",{
                "reference":ref,"section":section,
                "items":[{"id":o.id,"claim":c.statement[:850],
                          "objection":o.issue[:850]} for o,c in candidates],
                "task":"Classify each objection against the exact cited claim "
                       "and indexed RFC section; never assume an unsupported "
                       "dismissal is established."},synthesis=True)
            known={o.id:c for o,c in candidates}
            source=_flat(ref["excerpt"])
            if not isinstance(response,dict):
                continue
            for row in response.get("items",[]) or []:
                oid=row.get("id")
                if oid not in known or oid in outcomes:
                    continue
                verdict=row.get("verdict")
                quote=row.get("quote") or ""
                if not isinstance(quote,str):
                    quote=""
                normalized=_flat(quote)
                claim_text=_flat(known[oid].statement)
                in_reference=bool(normalized and normalized in source)
                in_claim=bool(normalized and normalized in claim_text)
                # Quoting the claim itself is NOT independent evidence that
                # an objection contradicts the RFC; require an RFC quote.
                # A valid objection requires an RFC quote; merely
                # parroting the attacked claim cannot establish validity.
                # Short generic substrings are not adequate grounding.
                enough=len(normalized)>=12
                allowed=enough and (
                    verdict=="valid" and in_reference or
                    verdict=="contradicts_reference" and in_reference or
                    verdict=="already_in_claim" and in_claim or
                    verdict=="out_of_scope" and (in_reference or in_claim))
                if not allowed:
                    verdict="unjudged"
                outcomes[oid]={"verdict":verdict,"section":section,
                               "quote":quote if allowed else "",
                               "grounded":bool(allowed),
                               "reason":str(row.get("reason") or "")[:350]}
            self.events.record("objection_judge_batch",
                section=section,submitted=len(candidates),
                returned=sum(o.id in outcomes for o,c in candidates),
                dismissed=sum(
                    o.id in outcomes and outcomes[o.id]["grounded"]
                    and outcomes[o.id]["verdict"] in {
                        "contradicts_reference","already_in_claim","out_of_scope"}
                    for o,c in candidates),
                unjudged=sum(
                    o.id not in outcomes or
                    outcomes[o.id]["verdict"]=="unjudged"
                    for o,c in candidates))
        return outcomes

    def _triage_revision_objections(self, question: str,
                                    rfc_refs: dict[str,dict]) -> tuple[list[dict],list[Objection]]:
        """Gate unsafe objections BEFORE revision or moderator exposure.

        Only narrow RFC-conflict patterns with a complete official section
        are withheld as RFC conflicts. Nondefinitional review noise is kept
        separately. Every raw objection stays in the run's audit ledger.
        """
        groups={"1_full_uniqueness":"3.1",
                "2_trusted_uniqueness":"3.3",
                "3_pseudorandomness":"3.4"}
        blockers={"contradicts_rfc_3_1_uniqueness_is_not_collision",
                  "contradicts_rfc_3_3_sk_known",
                  "contradicts_rfc_3_4_no_challenge_proof"}
        withheld,eligible=[],[]
        for objection in self.objections:
            claim=self.ledger.claims.get(objection.claim_id)
            topic=topic_of(claim.statement) if claim is not None else ""
            section=groups.get(topic)
            flags=(objection_conflicts(question,objection.id,
                                     objection.issue,topic)
                   if section in rfc_refs else [])
            kinds=[f["kind"] for f in flags if f["kind"] in blockers]
            noise=objection_scope_noise(question,objection.issue,topic)
            if kinds or noise:
                withheld.append({
                    "id":objection.id,"claim_id":objection.claim_id,
                    "kinds":kinds or ["nondefinitional_"+noise],
                    "rfc_section":section if kinds else None,
                    "issue":objection.issue,
                    "reference_complete":bool(kinds),
                    "reason":"rfc_conflict" if kinds else "out_of_scope"})
            else:
                eligible.append(objection)
        return withheld,eligible

    @staticmethod
    def _screen_revision_objections(
            objections: list[Objection], regex_withheld: list[dict],
            verdicts: dict[str,dict], *, require_grounded: bool
            ) -> tuple[list[dict],list[Objection],list[dict]]:
        """Grounded verdict overrides regex. Unknown claims never edit VRF games.

        Regex is only a fallback for missing/untrusted model comparisons.
        Every objection remains in the immutable audit collection.
        """
        by_id={item["id"]:item for item in regex_withheld}
        withheld,eligible,pending=[],[],[]
        for o in objections:
            row=verdicts.get(o.id,{})
            if row.get("grounded"):
                if row.get("verdict")=="valid":
                    eligible.append(o)
                    continue
                if row.get("verdict") in {
                        "contradicts_reference","already_in_claim","out_of_scope"}:
                    withheld.append({
                        "id":o.id,"claim_id":o.claim_id,
                        "issue":o.issue,"rfc_section":row.get("section"),
                        "kinds":["grounded_"+row["verdict"]],
                        "reason":row["verdict"],
                        "quote":row.get("quote",""),
                        "reference_complete":True})
                    continue
            fallback=by_id.get(o.id)
            if fallback:
                withheld.append(dict(fallback,
                    reason="regex_fallback_"+str(fallback.get("reason","rfc_conflict"))))
                continue
            if require_grounded:
                pending.append({"id":o.id,"claim_id":o.claim_id,
                                "issue":o.issue,"reason":"unjudged",
                                "reviewer_family":o.reviewer_family})
            else:
                # Preserve the Council's normal review mechanism for
                # non-definitional research, which may have no RFC at all.
                eligible.append(o)
        return withheld,eligible,pending

    def _apply_revised_claim(self, p: dict, cid: str, changed: str,
                             item: dict) -> None:
        """Attach only new [R#] source provenance; old evidence never follows."""
        revised=self.ledger.revise(cid,changed)
        revised.source_span=None  # never inherit the old anchor
        revised.anchor_method=None
        source_span=item.get("source_span")
        revised_ids=item.get("sentence_ids")
        updated_text=p.get("revised_approach","")
        exact_anchor=False
        if isinstance(updated_text,str) and updated_text:
            # The author should cite [R#] lines, not the old
            # [S#] proposal. Provenance is never a proof.
            numbered=(numbered_sentence_excerpt(
                updated_text,revised_ids,tag="R")
                if isinstance(revised_ids,list) else None)
            candidates=[]
            if isinstance(source_span,str) and source_span.strip():
                candidates.append(source_span)
            if locate_source_span(updated_text,changed) is not None:
                candidates.append(changed)
            for candidate_span in dict.fromkeys(candidates):
                try:
                    anchor=validate_anchor(
                        updated_text,changed,candidate_span,
                        assumptions=string_list(item,"assumptions"))
                except (ValueError,OutputError):
                    continue
                revised.source_span=anchor.source_span
                revised.anchor_method="revised_exact_quote"
                revised.assumptions=list(anchor.assumptions)
                revised.quantifiers=list(anchor.quantifiers)
                exact_anchor=True
                break
            if revised.source_span is None and numbered:
                revised.source_span=numbered
                revised.anchor_method="revised_sentence_ids"
                revised.assumptions=string_list(item,"assumptions")
            if revised.source_span is None and isinstance(source_span,str):
                quoted=locate_source_span(updated_text,source_span)
                if quoted is not None:
                    revised.source_span=quoted
                    revised.anchor_method="revised_quoted_span"
        if revised.source_span is None:
            self.warnings.append(cid+": revised claim has no exact "
                                 "source or valid [R#] citation")
            self.extra_obligations.append(
                cid+": revised statement needs a new exact source anchor")
        elif not exact_anchor:
            self.extra_obligations.append(
                cid+": revised quote/sentence provenance located, "
                "but quantifier and claim alignment remain unchecked")
        self.events.record("claim_revised",
            claim_id=cid,version=revised.version,
            source_anchor_verified=exact_anchor,
            provenance_located=bool(revised.source_span),
            anchor_method=revised.anchor_method)

    def _review_payload(self, question: str, proposal: dict,
                        *, recheck: bool = False) -> dict:
        """Bounded review input: claims and the exact sentences they cite.

        Do not send the full proposal, which duplicates the cited sentences
        and causes needless output truncation in free-tier reviewer models.
        """
        rows=[]
        for cid in proposal["claim_ids"]:
            claim=self.ledger.claims[cid]
            span=claim.source_span or ""
            rows.append({
                "id":cid,
                "statement":claim.statement[:1200],
                "cited_sentence":span[:1600],
                "source_truncated":len(span)>1600,
                "source_anchor_missing":not bool(span)})
        payload={"question":question,"proposal_id":proposal["id"],
                 "claims":rows}
        if recheck:
            payload["review_phase"]="independent_revision_recheck"
            payload["prior_objections"]=[
                {"id":o.id,"claim_id":o.claim_id,"issue":o.issue[:500]}
                for o in self.objections if o.proposal_id==proposal["id"]][:4]
        return payload

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
                if is_meta_claim(statement):
                    self.events.record("rival_meta_claim_skipped",
                        proposal_id=owner["id"],statement_prefix=statement[:90])
                    continue
                span=require_string(entry,"source_span")
                anchored=validate_anchor(answer,statement,span,
                           assumptions=string_list(entry,"assumptions"))
            except (OutputError,ValueError):
                continue
            # The rival may simply split an already-cited [S#] section
            # into individual sentences. Use source provenance, not similarity
            # of owner summaries, to avoid a dozen redundant re-extractions.
            # A rival-supplied sentence ID is not trusted without matching
            # the actual quoted span to the original source.
            source_ids=source_sentence_ids(owner["approach"],anchored.source_span)
            covered={sid for ids in owner.get("claim_sentence_ids",{}).values()
                     for sid in ids}
            if source_ids and set(source_ids)<=covered:
                self.events.record("rival_claim_duplicate_skipped",
                    proposal_id=owner["id"],
                    duplicate_of="covered_by_owner_claims",
                    source_sentence_ids=source_ids,
                    similarity_policy="owner_sentence_provenance",
                    semantic_equivalence="not_verified")
                continue
            owned=[self.ledger.claims[cid] for cid in owner["claim_ids"]
                   if cid in self.ledger.claims]
            duplicate=close_to_owner(statement,owned)
            near=duplicate or close_to_owner(statement,owned,threshold=0.85)
            if near:
                original=self.ledger.claims[near]
                if not original.source_span or original.needs_re_evaluation:
                    try:
                        # Confirm the rival span is truly present in the
                        # original answer; similarity is NOT verification.
                        recovered=validate_anchor(answer,original.statement,
                            anchored.source_span,assumptions=original.assumptions)
                    except ValueError:
                        # A rival assertion with different quantifiers/meaning
                        # must not be silently discarded.
                        duplicate=None
                    else:
                        if not original.source_span:
                            original.source_span=recovered.source_span
                            original.anchor_method="rival_sentence_match"
                            original.quantifiers=list(recovered.quantifiers)
                        original.needs_re_evaluation=True
                        self.events.record("claim_anchor_recovered",
                            claim_id=original.id,method="rival_sentence_match",
                            semantic_alignment="unchecked")
                        duplicate=near
            if duplicate:
                self.events.record("rival_claim_duplicate_skipped",
                    proposal_id=owner["id"],duplicate_of=duplicate,
                    similarity_policy="statement_similarity_only",
                    semantic_equivalence="not_verified")
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
        self._current_question=question
        self.events.record("run_started",question=question,mode=mode,
            pipeline="evidence",
            requirements=req.as_data(),role_assignment=asdict(self.assignment),
            debate_caps=self.caps, solver_strategies=self.solver_strategies,
            deadline_remaining=self.budget.remaining())
        # Reference is public and identical for every sealed, independent
        # proposal. Never include a truncated or unauthenticated RFC excerpt.
        rfc_refs=self._rfc_game_references(question)
        self.events.record("solver_rfc_references",
            sections=sorted(rfc_refs),
            missing_sections=[s for s in ("3.1","3.3","3.4") if s not in rfc_refs])
        proposals=[]
        compact_command_refs=self._cohere_proposal_references(rfc_refs)
        raw=await asyncio.gather(*[
            self._call(family,"proposal",{
                "question":question,"requirements":req.as_data(),
                "independent":True,"source_spans_required":True,
                "strategy":self.solver_strategies[family],
                "reference_sections":(
                    compact_command_refs if family=="command" else rfc_refs),
                "output_limits":(
                    {"max_claims":5,"max_approach_lines":5,
                     "be_concise":True} if family=="command" else None)})
            for family in self.solvers])
        for index,(family,body) in enumerate(zip(self.solvers,raw),1):
            if body is None:continue
            is_vrf=("vrf" in question.casefold() or
                    "verifiable random function" in question.casefold())
            # Self-referential claims are not domain claims for ANY question.
            # Also omit generic VRF summary lines that duplicate real claims.
            distinct=[c for c in body.get("claims",[])
                      if not is_meta_claim(c.get("statement","")) and
                      not (is_vrf and is_summary(c.get("statement","")))]
            removed=len(body.get("claims",[]))-len(distinct)
            if removed:
                self.events.record("summary_or_meta_claims_filtered",
                    family=family,removed=removed)
                if not distinct:
                    self.warnings.append(
                        "proposal/"+family+": no substantive claims after filtering")
                    continue
                body=dict(body,claims=distinct)
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
        # An isolated solver cannot constitute a full independent Council.
        # Keep source diagnostics, but do not spend quota on peer review,
        # revisions, repair, blind judge or final audit.
        if mode=="full" and len(proposals)<2:
            return await self._stop_for_independence(question,req,proposals)
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
            p["reviewer_family"]=peer  # Recheck by the actual original critic.
            review=await self._call(
                peer,"review",self._review_payload(question,p))
            if not review:continue
            try: rows=item_list(review,"objections")
            except OutputError:continue
            for raw_ob in rows[:4]:
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
        # Do not expose untrusted critic corrections to the author or the
        # moderator until their RFC-game meaning has been screened.
        regex_withheld,_=self._triage_revision_objections(
            question,rfc_refs)
        # ALL objections are judged, including regex-flagged criticisms.
        # Only a grounded "valid" result can influence authors on a VRF
        # definition question. Ungrounded/unseen judgments are UNJUDGED.
        self.grounded_objection_verdicts=await self._ground_objections(
            rfc_refs,self.objections)
        withheld,revision_objections,unjudged_before_revision=(
            self._screen_revision_objections(
                self.objections,regex_withheld,self.grounded_objection_verdicts,
                require_grounded=is_vrf_definition_question(question)))
        self.events.record("objections_unjudged_before_revision",
            ids=[o["id"] for o in unjudged_before_revision],
            retained_in_audit=True)
        for o in revision_objections:
            try:
                self.moderator.submit(Message("review:"+o.id,o.claim_id,
                    Act.CHALLENGE,o.reviewer_family,o.reviewer_family,
                    o.issue[:2400],step_ref=o.issue[:300]))
            except (EvidenceRejected,MessageCap):
                self.warnings.append("Review challenge not delivered: "+o.id)
        self.events.record("objections_withheld_from_revision",
            ids=[o["id"] for o in withheld],
            kinds=[o["kinds"] for o in withheld],
            rfc_sections=sorted({o["rfc_section"] for o in withheld
                                 if o["rfc_section"] is not None}),
            retained_in_audit=True)
        for p in proposals:
            if self.budget.debate_remaining()<=1:break
            related=[o for o in revision_objections if o.proposal_id==p["id"]]
            if not related:continue
            author=await self._call(p["family"],"revision",{
                "original_approach":p["approach"],
                "claims":[{"id":cid,"statement":self.ledger.claims[cid].statement}
                          for cid in p["claim_ids"]],
                "objections":[asdict(o) for o in related],
                "reference_sections":self._reference_for_claims(
                    p["claim_ids"],rfc_refs)})
            if not author:continue
            try:
                if isinstance(author.get("revised_approach"),str):
                    p["revised_approach"]=author["revised_approach"]
                for item in item_list(author,"revised_claims"):
                    cid=require_string(item,"claim_id")
                    if cid not in p["claim_ids"]:continue
                    changed=require_string(item,"statement")
                    if changed!=self.ledger.claims[cid].statement:
                        self._apply_revised_claim(p,cid,changed,item)
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
            reviewer=p.get("reviewer_family")
            if not reviewer:
                continue
            followup=await self._call(
                reviewer,"review",self._review_payload(question,p,recheck=True))
            if followup:
                try:
                    # Follow-up is a targeted recheck, not four more
                    # independent criticisms of the original submission.
                    for raw_ob in item_list(followup,"objections")[:2]:
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
                    "independent":True,"source_spans_required":True,
                    "reference_sections":(
                        compact_command_refs if p["family"]=="command" else rfc_refs),
                    "output_limits":(
                        {"max_claims":5,"max_approach_lines":5,
                         "be_concise":True} if p["family"]=="command" else None)})
                if sample:
                    # Exact prose equality is NOT a semantic stability test.
                    # Different generations should not automatically invalidate
                    # verified evidence, nor does identical prose prove a claim.
                    p["stability"]=(
                        "text_identical_unverified"
                        if sample.get("approach")==p["approach"]
                        else "semantic_stability_unassessed")
                    self.events.record("adaptive_sample",proposal_id=p["id"],
                        stability=p["stability"],
                        semantic_equivalence="not_checked",
                        evidence_invalidation="none_from_wording_alone")
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
            jobs=[]
            for idx,claim in enumerate(open_claims[:self.hunter_cap]):
                alternatives=[f for f in self.solvers if f!=claim.owner_family]
                if alternatives:
                    hunter=alternatives[idx%len(alternatives)]
                    jobs.append((claim,hunter,self.moderator.current_round))
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
            game_warnings=scan_vrf_games(question,[c])
            definition=definition_kind(question,c.statement)
            excerpt=None
            if definition is not None and self.paper_index is not None:
                try:
                    excerpt=self.paper_index.rfc_section_excerpt(
                        definition[1],max_chars=2400)
                except (ValueError,AttributeError):
                    excerpt=None
            suggestion=await self._call(repairer,"repair",{
                "claim_id":c.id,"claim":c.statement,"assumptions":c.assumptions,
                "obligations":[v for v in self.extra_obligations
                               if v.startswith(c.id+":")][:6],
                "warnings":[{"kind":v["kind"],"message":v["message"]}
                            for v in game_warnings],
                "reference":excerpt})
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
        advisory_findings=self._vrf_findings(question,proposals)
        if advisory_findings:
            self.events.record("advisory_game_red_flags",
                findings=advisory_findings,
                disclaimer="Heuristic checks; no independent proof or adjudication")
        brief=ResearchResult(research_question=question,
                             completion_status="partial")
        brief.hypotheses=list(dict.fromkeys(h for p in proposals for h in p["hypotheses"]))
        brief.proposed_experiments=list(dict.fromkeys(x for p in proposals for x in p["experiments"]))
        brief.supported_findings=[c.statement for c in self.ledger.claims.values()
                                  if c.status is ClaimStatus.SUPPORTED]
        brief.checked_source_ids=sorted(self.checked_sources)
        brief.proposed_approach=(
            proposals[0]["approach"] if len(proposals)==1 else
            "\n\n".join("Proposal "+p["id"]+" ("+p["family"]+"):\n"+
                         p["approach"] for p in proposals))
        open_claims=[c for c in self.ledger.claims.values()
                     if c.status in {ClaimStatus.PROPOSED,ClaimStatus.UNRESOLVED}]
        brief.proof_obligations=group_by_claim_id(
            self.extra_obligations+
            [c.id+": "+c.statement+" (not independently established)"
             for c in open_claims], self.ledger.claims)
        # Unverified claims are obligations, not actual reviewer objections.
        brief.unresolved_objections=list(dict.fromkeys(
            self.coverage+
            [o.id+": "+o.issue+" (not yet independently resolved)"
             for o in self.objections]))
        if mode=="full" and len(proposals)<len(self.solvers):
            brief.limitations.append(
                "Reduced independent proposal coverage: "+
                str(len(proposals))+"/"+str(len(self.solvers))+
                " configured solver families returned valid proposals")
            brief.next_actions.extend(self._missing_solver_actions(proposals))
        if brief.proof_obligations:
            brief.next_actions.append(
                "Check the listed claims against independent evidence before "
                "treating this proposal as a verified result")
        if any(c.source_span is None for c in open_claims):
            brief.next_actions.append(
                "Supply verbatim claim quotations from the original proposal")
        if advisory_findings:
            brief.limitations.append(
                "Automated VRF security-game checks found potential definition "
                "errors; these are advisory flags, not verified counterexamples")
            brief.next_actions.append(
                "Review flagged game definitions against RFC 9381 sections 3.1, "
                "3.3 and 3.4, then obtain independent cryptographic review")
        # Blind to model identities. Include complete blocker IDs and
        # compact, topic-grouped claim views with explicit truncation flags.
        warning_map={}
        for row in advisory_findings:
            key=row["claim_id"].split(":source")[0]
            warning_map.setdefault(key,[]).append(row["kind"])
        ledger_view=None
        try:
            ledger_view=blind_ledger(
                self.ledger,max_chars=12000,warning_kinds=warning_map)
        except ValueError:
            self.warnings.append(
                "Compact blind ledger still too large: skipping model judge "
                "rather than supplying a deceptive placeholder")
            self.events.record("judge_skipped",reason="judge_input_too_large")
        rfc_excerpts=[]
        if self.paper_index is not None and "vrf" in question.casefold():
            for section in ("3.1","3.3","3.4"):
                try:
                    excerpt=self.paper_index.rfc_section_excerpt(
                        section,max_chars=6000)
                except (AttributeError,ValueError):
                    excerpt=None
                if excerpt:
                    rfc_excerpts.append(excerpt)
        judge_payload={"ledger":ledger_view,
            "rfc_reference_excerpts":rfc_excerpts,
            "reference_limitations":"Verbatim excerpts establish provenance, "
                                   "not semantic entailment or construction security",
            "question_requirements":req.as_data(),
            "argument_map":[{"claim_id":x["claim_id"],"evidence_id":x["evidence_id"]}
                            for x in self.verified]}
        # Quick mode is a low-quota draft/verification preview, not peer
        # review. Use the deterministic evidence policy by default; opt in
        # to spending a model judge call with COUNCIL_QUICK_LLM_JUDGE=1.
        local_judge=(mode=="quick" and
                     os.getenv("COUNCIL_QUICK_LLM_JUDGE","0")!="1")
        if local_judge:
            candidate={"status":"unresolved","blocking":[],
                       "basis":["Deterministic local evidence policy"],
                       "partial_answer":brief.proposed_approach,
                       "cause":"blocking_claims"}
            self.events.record("quick_judge_skipped",reason="save_free_tier_quota")
            brief.judge_summary=(
                "Local evidence policy: claims require independently "
                "scoped verification; quick mode has no peer reviewers.")
        elif ledger_view is None:
            candidate=None
        else:
            # _call already retries a malformed judge response once.
            candidate=await self._call(
                self.judge_family,"judge",judge_payload,synthesis=True)
        judge_unavailable=(not local_judge and candidate is None)
        judge_input_too_large=(not local_judge and ledger_view is None)
        if judge_unavailable:
            failures=[w for w in self.warnings
                      if w.startswith("judge/"+self.judge_family+":")]
            reason=("compact ledger exceeds bounded model input"
                    if judge_input_too_large else
                    failures[-1].split(": ",1)[1] if failures else "no judge response")
            brief.judge_summary="Judge unavailable ("+reason[:220]+"); no blind-judge response."
            brief.limitations.append(
                "Blind judge unavailable; no model judgment completed")
            brief.next_actions.append(
                "Inspect judge provider failures (HTTP status and retry mode) "
                "before relying on a full-mode verdict")
        verdict=enforce_verdict(candidate or {"status":"unresolved",
            "cause":("judge_input_too_large" if judge_input_too_large
                     else "judge_error"),"basis":["Judge unavailable"],
            "partial_answer":None},self.ledger)
        partial=verdict.get("partial_answer")
        # A blind judge sees the claim ledger, not the author's complete prose.
        # Keep the original solver explanation as the proposed approach even
        # when the judge returns a valid but unhelpfully short summary.
        if (not local_judge and not judge_unavailable
                and isinstance(partial,str) and partial.strip()):
            brief.judge_summary=partial.strip()
        elif not local_judge and not judge_unavailable:
            self.events.record("judge_partial_fallback",
                               reason="missing_or_non_substantive_summary")
            brief.limitations.append(
                "Judge supplied no substantive summary; original solver proposal retained")
        composition=compose_answer(
            str(verdict.get("answer") or brief.proposed_approach or ""),
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
            prior_cause=verdict.get("cause")
            cause=(prior_cause if prior_cause in
                   {"judge_error","deadline","quota_contention",
                    "judge_input_too_large"} else
                   "definition_reference_only"
                   if is_vrf_definition_question(question) else
                   "composition_failure")
            verdict=enforce_verdict(dict(verdict,status="unresolved",
                cause=cause),self.ledger)
            if cause!="composition_failure":
                verdict["additional_causes"]=["composition_failure"]
        # Keep all judge blockers visible, but do not relabel them as
        # objections raised by a reviewer. The blocking IDs are in verdict.
        brief.proof_obligations=group_by_claim_id(
            brief.proof_obligations+
            [cid+": independent verification required"
             for cid in verdict["blocking"]
             if cid!="composition:1"], self.ledger.claims)
        # Consolidate before the optional auditor spends the remaining quota.
        topic_consolidation=(await self._consolidate_topics(question,advisory_findings)
                             if mode=="full" else [])
        audit=None
        issues=[]
        audit_advisories=[]
        if mode!="quick" and self.auditor_family is not None:
            # The auditor sees only model-authored research claims, source
            # excerpts and scoped evidence. Coordinator obligation strings
            # (e.g., "needs alignment review") must not be misattributed to
            # the solver and cannot themselves become an audit criticism.
            audit_material={
                "research_question":question,
                "proposed_approach":brief.proposed_approach,
                "hypotheses":brief.hypotheses,
                "claims":[{"id":c.id,"statement":c.statement,
                           "source_span":c.source_span,
                           "status":c.status.value,
                           "evidence":[{"id":e.id,"kind":e.kind.value,
                                        "outcome":e.outcome,
                                        "independently_checked":e.independently_checked}
                                       for eid in c.evidence_ids
                                       if (e:=self.ledger.evidence.get(eid)) is not None]}
                          for c in self.ledger.claims.values()
                          if not c.id.startswith("composition:")],
                "reviewer_objections":[{"id":o.id,"claim_id":o.claim_id,
                                        "issue":o.issue}
                                       for o in self.objections]}
            audit=await self._call(self.auditor_family,"audit",{
                "question":question,"requirements":req.as_data(),
                "blind_verdict":{"status":verdict.get("status"),
                                 "blocking":verdict.get("blocking",[])},
                "research_result":audit_material},synthesis=True)
        if audit:
            try:
                issues=string_list(audit,"issues")
                audit_advisories=scan_audit_issues(question,issues)
                existing={(row["claim_id"],row["kind"])
                          for row in advisory_findings}
                unique=[]
                for row in audit_advisories:
                    # Auditors may explicitly reference a model claim ID;
                    # use it to avoid printing an already-known warning.
                    ident=row["claim_id"]
                    match=re.fullmatch(r"audit:([0-9]+)",ident)
                    if match and int(match.group(1)) <= len(issues):
                        cited=re.search(r"\bp[0-9]+:(?:c|r)[0-9]+(?::repair)?\b",
                                        issues[int(match.group(1))-1])
                        if cited and cited.group() in self.ledger.claims:
                            row=dict(row,claim_id=cited.group())
                    key=(row["claim_id"],row["kind"])
                    if key not in existing:
                        unique.append(row)
                        existing.add(key)
                audit_advisories=unique
                if audit_advisories:
                    self.events.record("audit_game_red_flags",
                        findings=audit_advisories,
                        disclaimer="Heuristic scope warnings; auditor claims remain unverified")
                brief.unresolved_objections=list(dict.fromkeys(
                     brief.unresolved_objections+issues))
                brief.proposed_experiments=list(dict.fromkeys(
                     brief.proposed_experiments+string_list(audit,"suggested_checks")))
            except OutputError:self.warnings.append("Audit output malformed")
        elif mode!="quick":
            brief.limitations.append(
                "Independent auditor not assigned" if self.auditor_family is None
                else "Independent auditor unavailable; full-mode result lacks "
                     "the reserved independent audit stage")
            failures=[w for w in self.warnings
                      if self.auditor_family and
                      w.startswith("audit/"+self.auditor_family+":")]
            reason=failures[-1].split(": ",1)[1] if failures else "no audit response"
            if "unconfigured or free mode unconfirmed" in reason:
                brief.next_actions.append(
                    "Confirm an actual free allowance for the reserved auditor "+
                    str(self.auditor_family)+" before enabling that provider")
            else:
                brief.next_actions.append(
                    "Reserved auditor failed during this run ("+
                    reason[:200]+"); check provider health or retry later")
        # Audit criticisms also require independent RFC/claim quote checks.
        # The auditor cannot make an invalid game objection "true" by
        # merely listing it in its JSON. No calls are made without budget.
        audit_objections=[]
        for idx,issue in enumerate(issues,1):
            candidate_ids=re.findall(
                r"\bp[0-9]+:(?:c|r)[0-9]+(?::repair)?\b",issue)
            cid=next((key for key in candidate_ids
                      if key in self.ledger.claims),None)
            if cid:
                audit_objections.append(Objection(
                    "audit:"+str(idx),"audit",cid,
                    self.auditor_family or "audit",issue,"",""))
        audit_grounded=(await self._ground_objections(rfc_refs,audit_objections)
                       if audit_objections else {})
        self.grounded_objection_verdicts.update(audit_grounded)
        self.events.record("audit_objections_grounded",
            submitted=len(audit_objections),
            grounded=sum(bool(v.get("grounded"))
                         for v in audit_grounded.values()),
            unjudged=len(audit_objections)-sum(
                bool(v.get("grounded")) for v in audit_grounded.values()))
        # Categorize suspicious review/audit claims without throwing away
        # unverified objections or treating pattern matches as proofs.
        def target_text(cid):
            claim=self.ledger.claims.get(cid)
            return claim.statement if claim else ""
        all_objections=[{"id":o.id,"claim_id":o.claim_id,"source":"reviewer",
                         "topic":topic_of(self.ledger.claims[o.claim_id].statement)
                         if o.claim_id in self.ledger.claims else "",
                         "target_statement":target_text(o.claim_id),
                         "issue":o.issue} for o in self.objections]
        for i,issue in enumerate(issues if audit else [],1):
            match=re.search(r"\bp[0-9]+:(?:c|r)[0-9]+(?::repair)?\b",issue)
            cid=match.group() if match else None
            claim=self.ledger.claims.get(cid) if cid else None
            all_objections.append({
                "id":"audit:"+str(i),"source":"auditor",
                "claim_id":cid,
                "topic":topic_of(claim.statement) if claim else "",
                "target_statement":target_text(cid),
                "issue":issue})
        # One exclusive display section per objection, with grounded
        # verdicts taking precedence over regex (and over prior heuristics).
        grounded=self.grounded_objection_verdicts
        sections=presentation_sections(
            question,all_objections,withheld,grounded,
            require_grounded=is_vrf_definition_question(question))
        withheld=sections["withheld"]
        rfc_conflicts=sections["conflicts"]
        already_addressed=sections["addressed"]
        still_open=sections["open"]
        unjudged=sections["unjudged"]
        out_of_scope=sections["out_of_scope"]
        self.events.record("objection_display_deduplicated",
            raw_count=len(all_objections),
            displayed_count=sum(map(len,sections.values())),
            grounded_open=len(still_open),
            unjudged=len(unjudged),
            preserved_in_records=True)
        # Limit only the human-readable shortlist. Never discard raw records.
        prioritized=still_open
        displayed=prioritized[:8]
        omitted=max(0,len(prioritized)-len(displayed))
        brief.unresolved_objections=list(dict.fromkeys(
            self.coverage+
            [row["id"]+": "+row["issue"]+
             (" (source-quoted, model-advisory; not independently verified)"
              if row.get("advisory_status")=="grounded_valid" else
              " (not independently resolved)")+
             (" [similar objection IDs: "+", ".join(
                    str(i) for i in row["duplicate_ids"])+"]"
                 if row.get("duplicate_ids") else "")
             for row in displayed]+
            (["And "+str(omitted)+" additional unresolved objections; "
              "see unresolved_objections_all in structured output"]
             if omitted else [])))
        brief.completion_status=("partial" if proposals else "unresolved")
        brief.limitations=list(dict.fromkeys(brief.limitations+self.warnings))
        result={"research_result":brief.to_dict(),"proposals":proposals,
            "objections":[asdict(o) for o in self.objections],
            "objections_withheld_from_revision":withheld,
            "objections_unjudged_before_revision":unjudged_before_revision,
            "author_responses":[asdict(a) for a in self.author_responses],
            "claims":[asdict(c) for c in self.ledger.claims.values()],
            "evidence":[asdict(e) for e in self.ledger.evidence.values()],
            "verdict":verdict,"composition":asdict(composition),
            "requirements":req.as_data(),"actual_models":self.actual_models,
            "duplicate_suggestions":self.duplicate_suggestions,
            "stalemates":self.moderator.bus.stalemates(),
            "advisory_findings":advisory_findings,
            "audit_advisory_findings":audit_advisories,
            "rfc_conflicting_objections":rfc_conflicts,
            "already_addressed_objections":already_addressed,
            "open_objections":still_open,
            "unjudged_objections":unjudged,
            "unresolved_objections_all":prioritized,
            "unresolved_objections_display_omitted":omitted,
            "grounded_out_of_scope_objections":out_of_scope,
            "grounded_objection_verdicts":grounded,
            "topic_consolidation":topic_consolidation,
            "reference_checks":self.reference_checks,
            "judge_source":("local_policy" if local_judge else
                            "unavailable" if judge_unavailable else "model"),
            "role_coverage":{"requested_solvers":list(self.solvers),
                "valid_proposer_families":[p["family"] for p in proposals],
                "review_objection_count":len(self.objections),
                "independent_audit_completed":bool(audit) if mode!="quick" else False,
                "audit_family":self.auditor_family if mode!="quick" else None},
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
                 judge_family=JUDGE, solver_strategies=None, paper_index=None):
        super().__init__(transport,events,budget,requirements=requirements,
                         solvers=(solver,),translator_family=translator_family,
                         judge_family=judge_family,
                         solver_strategies=solver_strategies,
                         paper_index=paper_index,
                         max_claims=4,hunter_cap=0,
                         enable_coverage=False,enable_relevance=False,
                         critics=(),adaptive_seeds=False,enable_repairs=False)

    async def run(self,question:str,*,mode:str="quick"):
        return await super().run(question,mode="quick")

"""Regression tests for single-proposal result recovery and model reliability.

No external model calls; all statements are advisory, not scientific proof.
"""
from __future__ import annotations
import asyncio
from types import SimpleNamespace
import unittest

from council.full import FullCouncilRunner
from council.models import Claim, ClaimLedger
from council.requirements import Requirements
from council.plan_sanity import is_plan_instead_of_answer
from council.structured import response_format
from council.vrf_sanity import scan_vrf_games
from council.workflow import CouncilRunner


QUESTION="Explain full uniqueness, trusted uniqueness, and pseudorandomness security games for a lattice-based VRF."


class SingleProposalReliabilityTests(unittest.TestCase):
    def test_one_proposal_still_gets_three_advisory_topics_and_one_audit(self):
        ledger=ClaimLedger()
        versions=[
            ("p3:c1","Full uniqueness: the adversary chooses a PK and one input, "
                      "and finds two accepted proofs with different outputs.",
             "Full uniqueness covers a PK and one input with different accepted outputs."),
            ("p3:c2","Trusted uniqueness: the honestly generated PK and SK "
                      "are both given to the adversary.",
             "Trusted uniqueness gives honestly generated PK and SK to the adversary."),
            ("p3:c3","Full pseudorandomness gives a fresh challenge output "
                      "without proof and ordinary oracle access.",
             "Pseudorandomness returns a fresh challenge output without proof."),
        ]
        refs={"3.1":versions[0][2],"3.3":versions[1][2],"3.4":versions[2][2]}
        for cid,statement,_ in versions:
            ledger.add_claim(Claim(cid,1,statement,"nemotron"))
        calls=[]
        rows=[]
        class Index:
            def rfc_section_excerpt(self,section,max_chars=6000):
                return {"section":section,"excerpt":refs[section],
                        "truncated":False,"document_id":"rfc9381"}
        class Budget:
            def debate_remaining(self):
                return 100
        class Events:
            def record(self,event,**kwargs):
                rows.append((event,kwargs))
        async def fake_call(family,role,payload,synthesis=False):
            calls.append((role,family))
            if role=="topic_judge":
                section=payload["section"]
                cid=next(v[0] for v in versions if v[2]==refs[section])
                return {"topic":payload["topic"],
                        "versions":[{"id":cid,"status":"matches",
                                     "reference_quote":refs[section],
                                     "reason":"Source-aligned"}],
                        "best_version_id":cid,"summary":"Source-aligned definition"}
            if role=="audit":
                return {"issues":["An oracle freshness condition should be explicit."],
                        "suggested_checks":[]}
            raise AssertionError(role)
        state=SimpleNamespace(
            ledger=ledger,solvers=("gpt-oss","command","nemotron"),
            paper_index=Index(),budget=Budget(),events=Events(),
            extra_obligations=[],reference_checks=[],warnings=[],
            judge_family="gemini",auditor_family="gemma",
            actual_models=[],
            _call=fake_call,
            _vrf_findings=lambda q,ps:[],
            _missing_solver_actions=lambda ps:["Retry failed proposal family"],
            _rfc_game_references=lambda q:{},
        )
        state._consolidate_topics=lambda q,flags: FullCouncilRunner._consolidate_topics(
            state,q,flags)
        proposal={"id":"p3","family":"nemotron","approach":"[S1] Full uniqueness ...",
                  "hypotheses":[],"claim_ids":[cid for cid,_,_ in versions],
                  "experiments":[]}
        result=asyncio.run(FullCouncilRunner._stop_for_independence(
            state,QUESTION,Requirements(QUESTION),[proposal]))
        self.assertEqual(result["research_result"]["completion_status"],
                         "partial_single_proposal")
        self.assertEqual(result["verdict"]["status"],"unresolved")
        self.assertEqual(result["verdict"]["cause"],"insufficient_independence")
        self.assertEqual([r["best_version_id"] for r in result["topic_consolidation"]],
                         ["p3:c1","p3:c2","p3:c3"])
        self.assertEqual([role for role,_ in calls],
                         ["topic_judge"]*3+["audit"])
        self.assertTrue(result["role_coverage"]["independent_audit_completed"])
        self.assertEqual(result["role_coverage"]["valid_proposer_families"],
                         ["nemotron"])
        self.assertFalse(any(r["verified"] for r in result["topic_consolidation"]))
        self.assertTrue(any(x=="single_proposal_assessment_completed"
                            for x,data in rows))

    def test_plan_retry_is_reason_specific(self):
        messages=[]
        plan="[S1] Define full uniqueness. [S2] Outline trusted uniqueness. [S3] Describe pseudorandomness."
        answer=("[S1] Full uniqueness is one input with two accepted outputs. "
                "[S2] Trusted uniqueness gives the adversary honestly generated keys. "
                "[S3] Pseudorandomness requires a fresh challenge output without its proof.")
        class Transport:
            async def complete(self,family,message,budget,role,synthesis=False):
                messages.append(message)
                approach=plan if len(messages)==1 else answer
                import json
                obj={"approach":approach,
                     "claims":[{"id":"c1","statement":"Full uniqueness is one input with two outputs.",
                                "source_span":"Full uniqueness is one input with two accepted outputs.",
                                "sentence_ids":[1]}],
                     "hypotheses":[],"experiments":[]}
                return SimpleNamespace(text=json.dumps(obj),
                                       provider="Groq",model="openai/gpt-oss-120b",
                                       prompt_hash="test")
        events=[]
        fake=SimpleNamespace(
            transport=Transport(),budget=SimpleNamespace(
                allowed=lambda *a,**kw:100),
            events=SimpleNamespace(record=lambda *a,**kw:events.append((a,kw))),
            actual_models=[],warnings=[])
        reply=asyncio.run(CouncilRunner._call(fake,"gpt-oss","proposal",
                             {"question":QUESTION}))
        self.assertEqual(reply["approach"],answer)
        self.assertEqual(len(messages),2)
        self.assertIn("previous response was a list of tasks",messages[1])
        self.assertIn("ACTUAL SECURITY GAME RULES",messages[1])
        self.assertTrue(any(e[0]=="format_retry_requested" for e in events))

    def test_plan_heuristic_accepts_substantive_definitions_with_define_verb(self):
        approach=("[S1] Define full uniqueness as the game in which the "
                  "adversary produces one PK and two proofs verifying different "
                  "outputs for one input. "
                  "[S2] Describe trusted uniqueness as the game in which the "
                  "adversary receives both honestly generated PK and SK. "
                  "[S3] State pseudorandomness as the game in which the "
                  "challenger returns a real or random target output without proof.")
        self.assertFalse(is_plan_instead_of_answer(QUESTION,approach))
        checklist=("[S1] Define the full uniqueness game. "
                   "[S2] Describe trusted uniqueness. "
                   "[S3] Outline pseudorandomness.")
        self.assertTrue(is_plan_instead_of_answer(QUESTION,checklist))

    def test_cohere_compact_source_is_marked_incomplete(self):
        refs={section:{"section":section,"excerpt":("RFC section "+section+
              " states the security game. "+"x"*4000),
              "truncated":False,"source_uri":"https://www.rfc-editor.org/rfc/rfc9381.txt"}
              for section in ("3.1","3.3","3.4")}
        short=FullCouncilRunner._cohere_proposal_references(refs)
        self.assertEqual(set(short),set(refs))
        self.assertLessEqual(sum(len(v["excerpt"]) for v in short.values()),2800)
        for section,row in short.items():
            self.assertTrue(row["truncated"])
            self.assertTrue(refs[section]["excerpt"].startswith(row["excerpt"]))
            self.assertIn("drafting context",row["excerpt_purpose"])
            self.assertFalse(refs[section]["truncated"])
        # Cohere proposal is already constrained to JSON Schema.
        structured=response_format("Cohere","command-a-03-2025","proposal")
        self.assertEqual(structured["type"],"cohere_json")
        self.assertIn("schema",structured)

    def test_scoped_warnings_ignore_healthy_p3_proposal(self):
        claims=[
            ("p3:c1","Full uniqueness (§3.1) is a game where an adversary "
              "chooses a public key PK, alpha, and pi1,pi2 with beta1 != beta2."),
            ("p3:c2","Trusted uniqueness (§3.3) is the same game as full "
              "uniqueness except honest keys PK and SK are generated and both "
              "given to the adversary."),
            ("p3:c3","Full pseudorandomness (§3.4) gives an adversary PK and "
              "an oracle on adaptively chosen inputs returning real "
              "(beta', pi') pairs, then gives a challenge beta* either real "
              "or uniform without its proof."),
            ("p3:c4","Selective pseudorandomness (§3.4) weakens the game by "
              "requiring the adversary to commit to alpha* before PK and "
              "oracle access."),
            ("p3:c5","Lattice VRFs instantiate uniqueness under SIS "
              "assumptions and pseudorandomness under decisional LWE "
              "hardness with no named construction.")]
        warnings=scan_vrf_games(QUESTION,[
            SimpleNamespace(id=cid,statement=claim) for cid,claim in claims])
        kinds_by_id={}
        for row in warnings:
            kinds_by_id.setdefault(row["claim_id"],set()).add(row["kind"])
        self.assertNotIn("full_uniqueness_key_choice_unspecified",
                         kinds_by_id.get("p3:c2",set()))
        self.assertNotIn("oracle_distribution_conflation",
                         kinds_by_id.get("p3:c3",set()))
        self.assertNotIn("pseudorandomness_freshness_unspecified",
                         kinds_by_id.get("p3:c4",set()))
        self.assertFalse(kinds_by_id.get("p3:c5",set()))
        # Full pseudorandomness really is missing explicit target freshness.
        self.assertIn("pseudorandomness_freshness_unspecified",
                      kinds_by_id.get("p3:c3",set()))


if __name__=="__main__":
    unittest.main()

"""Offline regressions for 2026-11-10 attached Phase-A review.

Passing these tests does not establish live provider availability, general
correctness of model-translated math or security-game theorem validity.
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from council.budget import RunBudget
from council.events import EventStore
from council.final_answers import (extract_final_answer,normalize_answer,
                                   proposal_answers)
from council.full import FullCouncilRunner
from council.models import (Claim,ClaimLedger,ClaimStatus,Evidence,EvidenceKind)
from council.schemas import validate
from council.structured import PROPOSAL_SCHEMA,response_format
from council.translate import plan
from council.verify.ladder import verify
from council.verify.sandbox import SandboxResult
from council.verify.author_check import recompute_answer


def runner(events):
    return FullCouncilRunner(None,events,RunBudget.start(60,reserve=3),
                             solvers=("gpt-oss",),hunter_cap=0,
                             enable_coverage=False,enable_repairs=False)


def proposal_body(final="42"):
    return {
        "approach":"[S1] We compute the requested result explicitly.",
        "final_answer":final,
        "claims":[{"id":"c1","statement":"The computation should be exact",
                   "source_span":"We compute the requested result explicitly.",
                   "sentence_ids":[1]}],
        "hypotheses":[],"experiments":[],
        "artifact":{"kind":"none","code":"","valid_examples":[],
                    "invalid_examples":[]}
    }


class ExplicitOutputTests(unittest.TestCase):
    def test_provider_contract_requires_scalar_final_and_baselines_plaintext(self):
        self.assertIn("final_answer",PROPOSAL_SCHEMA["required"])
        self.assertIsNone(response_format("Groq","openai/gpt-oss-120b","baseline"))
        self.assertIsNone(response_format("Groq","openai/gpt-oss-120b","baseline_vote6"))
        self.assertIsNone(response_format("Cohere","command-a-03-2025","baseline"))
        self.assertIsNotNone(response_format("Groq","openai/gpt-oss-120b","proposal"))
        self.assertEqual(validate("proposal",proposal_body())["final_answer"],"42")

    def test_scalar_extractor_reads_last_explicit_label_even_midline(self):
        self.assertEqual(extract_final_answer(
            "[S1] Multiply. [S2] These are equal for real x. Final answer: yes"),"yes")
        self.assertEqual(extract_final_answer(
            "Total = 106\nFinal answer: 106"),"106")
        self.assertEqual(extract_final_answer(
            "Final answer: no. Correction: Final answer: yes"),"yes")
        self.assertIsNone(extract_final_answer(
            "[S1] Expand.\n[S2] Compare."))
        self.assertEqual(normalize_answer(" 688 "), "688")
        self.assertIsNone(normalize_answer("688 because 98*7+2"))

    def test_revision_accepts_list_of_strings_only(self):
        out=validate("revision",{
            "revised_approach":["[R1] Step 1","[R2] Step 2"],
            "responses":[],"revised_claims":[]})
        self.assertEqual(out["revised_approach"],
                         "[R1] Step 1\n[R2] Step 2")
        with self.assertRaises(ValueError):
            validate("revision",{"revised_approach":[1,2]})

    def test_proposal_persists_final_answer_separately_from_plan(self):
        with TemporaryDirectory() as d, EventStore(Path(d),"proposal") as events:
            r=runner(events)
            p=r._proposal("gpt-oss",validate("proposal",proposal_body("13")),1)
            self.assertEqual(p["final_answer"],"13")
            self.assertIsNone(extract_final_answer(p["approach"]))
            self.assertEqual(proposal_answers([p],r.ledger)[1],{"p1":"13"})


class AliasArtifactTests(unittest.TestCase):
    def test_arithmetic_aliases_and_conflicts(self):
        p=plan("c1",1,"arithmetic",scope="98*7+2")
        self.assertEqual(verify(p,{"expression":"98*7+2",
                                   "expected_int":688}).outcome,"pass")
        self.assertEqual(verify(p,{"expression":"98*7+2",
                                   "expected":689}).outcome,"fail")
        self.assertEqual(verify(p,{"expression":"98*7+2",
                                   "expected":688,"expected_int":689}).outcome,
                         "error")
        self.assertEqual(verify(p,{"expression":"98*7+2",
                                   "expected":"688.4"}).outcome,"error")

    def test_symbolic_field_aliases(self):
        p=plan("c1",1,"identity",scope="identity")
        with patch("council.verify.ladder.identity",
                   return_value=SimpleNamespace(outcome="pass")) as mocked:
            result=verify(p,{"lhs":"(x+1)*(x+5)",
                             "rhs":"x**2+6*x+5"})
        self.assertEqual(result.outcome,"pass")
        mocked.assert_called_once_with("(x+1)*(x+5)","x**2+6*x+5")
        self.assertEqual(verify(p,{"left":"x","lhs":"y",
                                   "right":"x"}).outcome,"error")


class AuthorConsistencyTests(unittest.TestCase):
    def test_printed_number_and_dictionary_are_compared_in_sandbox(self):
        with patch("council.verify.author_check.run_python",
                   return_value=SandboxResult("ok","sandbox completed",
                                              stdout="688\n")) as run:
            self.assertEqual(recompute_answer("print(98*7+2)","688")[0],"pass")
            self.assertEqual(recompute_answer("print(98*7+2)","689")[0],"fail")
            self.assertEqual(run.call_args.kwargs["expect_pass_json"],False)
        with patch("council.verify.author_check.run_python",
                   return_value=SandboxResult("ok","sandbox completed",
                                              stdout="{'answer': 13}\n")):
            self.assertEqual(recompute_answer(
                "print({'answer': 13})","13")[0],"pass")
        with patch("council.verify.author_check.run_python",
                   return_value=SandboxResult("error","bubblewrap_unavailable")):
            self.assertEqual(recompute_answer("print(1)","1")[0],"error")

    def test_self_written_code_never_supports_answer_claim(self):
        async def check():
            with TemporaryDirectory() as d, EventStore(Path(d),"selftest") as events:
                r=runner(events)
                body=validate("proposal",proposal_body("688"))
                p=r._proposal("gpt-oss",body,1)
                p["artifact"]={
                    "kind":"python","code":"print(98*7+2)",
                    "valid_examples":[],"invalid_examples":[]}
                r._register_answer_claim(p,"What is 98*7+2?")
                with patch("council.verify.author_check.run_python",
                           return_value=SandboxResult(
                               "ok","sandbox completed",stdout="688\n")):
                    await r._run_author_artifact(p)
                c=r.ledger.claims[p["answer_claim_id"]]
                ev=r.ledger.evidence[c.evidence_ids[0]]
                self.assertEqual(ev.outcome,"pass")
                self.assertFalse(ev.independently_checked)
                self.assertEqual(ev.checker_kind,"author_recompute")
                self.assertEqual(c.status,ClaimStatus.PROPOSED)
                self.assertIsNone(proposal_answers([p],r.ledger)[0])
        asyncio.run(check())


class AnswerScopeTests(unittest.TestCase):
    def test_supported_answer_with_unverified_explanation_and_no_contradiction(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:c1",1,"Explanatory","gpt-oss"))
        ledger.add_claim(Claim("p1:answer",1,"6*7 = 42","gpt-oss"))
        ledger.attach(Evidence("e1","p1:answer",1,EvidenceKind.TEST,"pass",
                               "6*7","hash1",independently_checked=True))
        p={"id":"p1","final_answer":"42",
           "claim_ids":["p1:c1","p1:answer"],
           "answer_claim_id":"p1:answer"}
        self.assertEqual(proposal_answers([p],ledger)[0],"42")
        ledger.claims["p1:c1"].status=ClaimStatus.CONTRADICTED
        self.assertIsNone(proposal_answers([p],ledger)[0])
        ledger.claims["p1:c1"].status=ClaimStatus.PROPOSED
        ledger.claims["p1:answer"].needs_re_evaluation=True
        self.assertIsNone(proposal_answers([p],ledger)[0])

    def test_author_only_pass_does_not_mark_answer_verified(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:answer",1,"6*7=42","gpt-oss"))
        ledger.attach(Evidence("e1","p1:answer",1,EvidenceKind.TEST,"pass",
                               "author code","h",independently_checked=False))
        p={"id":"p1","final_answer":"42","answer_claim_id":"p1:answer",
           "claim_ids":["p1:answer"]}
        self.assertIsNone(proposal_answers([p],ledger)[0])


class TranslationPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_reworded_claim_reaches_translator_without_self_certification(self):
        with TemporaryDirectory() as d, EventStore(Path(d),"reword") as events:
            r=runner(events)
            r._current_question="Compute a total"
            c=Claim("p1:c1",1,"98*7+2 = 688","gpt-oss",
                    source_span="A total of 688 units",
                    needs_re_evaluation=True)
            r.ledger.add_claim(c)
            calls=[]
            async def fake(family,role,payload,**kwargs):
                calls.append((family,role,payload))
                return {"claim_kind":"arithmetic","scope":"98*7+2",
                        "artifact":{"expression":"98*7+2","expected_int":688}}
            r._call=fake
            await r._translate_and_check(c)
            self.assertTrue(calls)
            self.assertEqual(c.status,ClaimStatus.PROPOSED)
            self.assertTrue(r.ledger.evidence)
            self.assertFalse(next(iter(r.ledger.evidence.values())).independently_checked)

    async def test_direct_user_expression_can_be_independently_checked(self):
        with TemporaryDirectory() as d, EventStore(Path(d),"literal") as events:
            r=runner(events)
            r._current_question="What is 98*7+2?"
            body=proposal_body("688")
            p=r._proposal("gpt-oss",body,1)
            r._register_answer_claim(p,r._current_question)
            answer=r.ledger.claims[p["answer_claim_id"]]
            self.assertEqual(answer.statement,"98*7+2 = 688")
            self.assertFalse(answer.needs_re_evaluation)
            async def fake(family,role,payload,**kwargs):
                self.assertEqual(payload["question"],"What is 98*7+2?")
                return {"claim_kind":"arithmetic","scope":"98*7+2",
                        "artifact":{"expression":"98*7+2","expected":688}}
            r._call=fake
            await r._translate_and_check(answer)
            self.assertEqual(answer.status,ClaimStatus.SUPPORTED)
            self.assertEqual(proposal_answers([p],r.ledger)[0],"688")

    async def test_quick_mode_one_translation_attempt(self):
        with TemporaryDirectory() as d, EventStore(Path(d),"quick") as events:
            r=runner(events)
            r._active_mode="quick"
            r._quick_translation_calls=0
            r._current_question="Compute a total"
            claim=Claim("p1:c1",1,"98*7+2 = 688","gpt-oss",
                        source_span="98*7+2 = 688")
            r.ledger.add_claim(claim)
            sent=[]
            async def reject(family,role,payload,**kwargs):
                sent.append(family)
                return None
            r._call=reject
            await r._translate_and_check(claim)
            await r._translate_and_check(claim)
            self.assertEqual(len(sent),1)


class ReviewerAndFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_reviewer_label_removed_but_provenance_still_checked(self):
        with TemporaryDirectory() as d, EventStore(Path(d),"rival") as events:
            r=runner(events)
            source="[S1] Do arithmetic.\n[S2] Trusted uniqueness assumes honest keys."
            owner={"id":"p1","family":"gpt-oss","approach":source,
                   "answer":source,"claim_ids":[],
                   "claim_sentence_ids":{}}
            async def extract(family,role,payload,**kwargs):
                return {"claims":[{
                    "id":"c1",
                    "statement":"[S2] Trusted uniqueness assumes honest keys.",
                    "source_span":"Trusted uniqueness assumes honest keys.",
                    "assumptions":[],"depends_on":[]}]}
            r._call=extract
            await r._extract_rival(owner,"command")
            own=[c for c in r.ledger.claims.values()
                 if c.id.startswith("p1:r")]
            self.assertEqual(len(own),1)
            self.assertEqual(own[0].statement,
                             "Trusted uniqueness assumes honest keys.")

    async def test_fallback_explicit_label_creates_answer_claim(self):
        with TemporaryDirectory() as d, EventStore(Path(d),"fallback") as events:
            r=runner(events)
            p=r._proposal("gpt-oss",proposal_body(""),1)
            p["approach"]="[S1] 98*7+2 gives an integer.\nFinal answer: 688"
            r._register_answer_claim(p,"What is 98*7+2?")
            self.assertEqual(p["final_answer"],"688")
            self.assertIn("p1:answer",r.ledger.claims)

    async def test_author_code_disagreement_prevents_verification(self):
        with TemporaryDirectory() as d, EventStore(Path(d),"conflict") as events:
            r=runner(events)
            p=r._proposal("gpt-oss",proposal_body("688"),1)
            p["artifact"]={"kind":"python","code":"print(689)",
                           "valid_examples":[],"invalid_examples":[]}
            r._register_answer_claim(p,"What is 98*7+2?")
            claim=r.ledger.claims[p["answer_claim_id"]]
            r.ledger.attach(Evidence("e1",claim.id,1,EvidenceKind.TEST,"pass",
                                     "98*7+2","h",independently_checked=True))
            self.assertEqual(proposal_answers([p],r.ledger)[0],"688")
            with patch("council.verify.author_check.run_python",
                       return_value=SandboxResult(
                           "ok","sandbox completed",stdout="689\n")):
                await r._run_author_artifact(p)
            self.assertTrue(p["author_inconsistency"])
            self.assertIsNone(proposal_answers([p],r.ledger)[0])


class ScoringAndCodeArtifactTests(unittest.TestCase):
    def test_match_expected_accepts_inline_labeled_scalar_and_rejects_prose(self):
        from answer_validation import matches_expected
        self.assertTrue(matches_expected(
            "[S1] Expanded. [S2] They are identical. Final answer: yes","yes"))
        self.assertTrue(matches_expected(
            "Total is 107; Final answer: 106","106"))
        self.assertFalse(matches_expected(
            "There are 106 units, but I did not compute the final answer","106"))
        self.assertFalse(matches_expected(
            "[S1] Difference is nonzero. Final answer: no","yes"))

    def test_answer_claim_cannot_certify_unrelated_reported_final_answer(self):
        ledger=ClaimLedger()
        c=Claim("p1:answer",1,"98*7+2 = 688","gpt-oss")
        ledger.add_claim(c)
        ledger.attach(Evidence("e1",c.id,1,EvidenceKind.TEST,"pass",
                               "98*7+2","hash",independently_checked=True))
        p={"id":"p1","family":"gpt-oss","final_answer":"689",
           "answer_claim_id":c.id,"claim_ids":[c.id]}
        self.assertIsNone(proposal_answers([p],ledger)[0])

    def test_code_task_prefers_function_from_proposal_artifact(self):
        from eval.execute import run_task
        class DummyCouncil:
            def __init__(self,*args,**kwargs):
                pass
            async def run(self,*args,**kwargs):
                return {"research_result":{"completion_status":"partial"},
                        "candidate_answers":{"p1":"3"},"final_answer":None,
                        "verdict":{"status":"unresolved"},
                        "composition":{"outcome":"unchecked"},
                        "proposals":[{
                            "id":"p1","approach":"[S1] Here is the code.",
                            "answer":"Final answer: 3",
                            "artifact":{"code":"def f(xs):\n    return sum(xs)"}}]}
        class FakeEvents:
            def replay(self):
                return []
        async def act():
            with patch("eval.execute.FullCouncilRunner",DummyCouncil), \
                 patch("eval.execute.hidden_case_outcome",
                       return_value="pass") as hidden:
                rows=await run_task(
                    {"id":"code","kind":"code","prompt":"Implement f(xs)",
                     "expected":"3",
                     "hidden_spec":{"cases":[{"input":[1,2],"expected":3}]}},
                    object(),FakeEvents(),deadline=30,run_baselines=False)
            return rows,hidden.call_args
        rows,called=asyncio.run(act())
        self.assertEqual(rows[0]["correct"],1)
        self.assertIn("def f(xs):",called.args[0])
        self.assertEqual(rows[0]["code_hidden_outcome"],"pass")
        self.assertEqual(rows[0]["verified"],0)


if __name__=="__main__":
    unittest.main()

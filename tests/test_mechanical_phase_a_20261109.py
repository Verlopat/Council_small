"""Phase-A mechanics: free-tier fallback, safe self-checks and honest scores.

All checks are offline. This file deliberately mocks untrusted sandbox runs;
passing it cannot establish that bubblewrap works on an external laptop.
"""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from answer_validation import matches_expected
from council.budget import RunBudget
from council.events import EventStore
from council.final_answers import extract_final_answer,proposal_answers
from council.full import FullCouncilRunner
from council.models import Claim,ClaimLedger,ClaimStatus,EvidenceKind
from council.quota import QuotaScheduler,QuotaContention
from council.verify.sandbox import SandboxResult
from council.schemas import validate
from council.structured import PROPOSAL_SCHEMA
from council.judge import normalize_topic_judgment
from eval.code_tasks import extract_function_source,hidden_case_outcome
from eval.generate_tasks import build
from eval.run_eval import paired_mode_comparison


class MechanicalEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_translator_falls_back_and_records_actual_family(self):
        with TemporaryDirectory() as folder:
            with EventStore(Path(folder),"fallback") as events:
                runner=FullCouncilRunner(
                    None,events,RunBudget.start(120,20),
                    enable_coverage=False,enable_repairs=False,
                    hunter_cap=0)
                runner._current_question="Check the equality"
                claim=Claim("p1:c1",1,"2+2=4","gpt-oss",
                            source_span="2+2=4")
                runner.ledger.add_claim(claim)
                calls=[]
                async def respond(family,role,payload,**kwargs):
                    calls.append((family,role))
                    if family=="glm":
                        return None
                    if family=="command":
                        return {"claim_kind":"arithmetic","scope":"2+2=4",
                                "artifact":{"expression":"2+2","expected":4}}
                    raise AssertionError(f"Unexpected translator: {family}")
                runner._call=respond
                await runner._translate_and_check(claim)
                self.assertEqual(calls,[("glm","translate"),("command","translate")])
                self.assertEqual(runner._translator_used["p1:c1"],"command")
                self.assertEqual(runner._translators_down,{"glm"})
                self.assertEqual(claim.status,ClaimStatus.SUPPORTED)
                self.assertTrue(any(e.independently_checked
                                    for e in runner.ledger.evidence.values()))

    async def test_author_generated_test_cannot_self_certify(self):
        with TemporaryDirectory() as folder:
            with EventStore(Path(folder),"author") as events:
                runner=FullCouncilRunner(
                    None,events,RunBudget.start(100,20),hunter_cap=0)
                claim=Claim("p1:c1",1,"Conjecture about sums","gpt-oss")
                runner.ledger.add_claim(claim)
                proposal={"id":"p1","claim_ids":["p1:c1"],
                          "artifact":{"kind":"python",
                                      "code":'import json\nprint(json.dumps({"pass": True}))',
                                      "valid_examples":[],"invalid_examples":[]}}
                with patch("council.verify.sandbox.run_python",
                           return_value=SandboxResult("pass","sandbox completed")) as mock:
                    await runner._run_author_artifact(proposal)
                mock.assert_called_once()
                evidence=list(runner.ledger.evidence.values())
                self.assertEqual(len(evidence),1)
                self.assertEqual(evidence[0].kind,EvidenceKind.TEST)
                self.assertEqual(evidence[0].outcome,"pass")
                self.assertFalse(evidence[0].independently_checked)
                self.assertEqual(claim.status,ClaimStatus.PROPOSED)
                self.assertIn("author_artifact_checked",
                              [e["event"] for e in events.replay()])


class AnswerAndEvaluationTests(unittest.TestCase):
    def test_final_answer_candidate_and_verified_separated(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:c1",1,"2+2=4","gpt-oss"))
        proposal=[{"id":"p1","answer":"The answer is 4",
                   "claim_ids":["p1:c1"]}]
        self.assertEqual(proposal_answers(proposal,ledger),
                         (None,{"p1":"4"}))
        ledger.claims["p1:c1"].status=ClaimStatus.SUPPORTED
        self.assertEqual(proposal_answers(proposal,ledger),
                         ("4",{"p1":"4"}))
        ledger.claims["p1:c1"].needs_re_evaluation=True
        self.assertIsNone(proposal_answers(proposal,ledger)[0])

    def test_conservative_extraction_and_symbolic_truth(self):
        self.assertEqual(extract_final_answer("Answer: 12,193"),"12193")
        self.assertEqual(extract_final_answer("2 + 2 = 4"),"4")
        self.assertEqual(extract_final_answer("Final answer: no"),"no")
        self.assertIsNone(extract_final_answer(
            "This construction has 2 keys and 3 proofs"))
        self.assertTrue(matches_expected(
            "Proof omitted.\nFinal answer: no","no"))
        self.assertTrue(matches_expected("The answer is yes","true"))
        self.assertFalse(matches_expected(
            "The answer is no","yes"))

    def test_generated_cases_include_negative_identites_and_hidden_code_edges(self):
        for split in ("dev","heldout"):
            rows=build(per_kind=30,split=split)
            symbolic=[x for x in rows if x["kind"]=="symbolic"]
            self.assertEqual(sum(x["expected"]=="no" for x in symbolic),9)
            code=[x for x in rows if x["kind"]=="code"]
            self.assertTrue(all(
                any(not case["input"] for case in r["hidden_spec"]["cases"])
                for r in code))
            path=Path(__file__).resolve().parents[1]/"eval"/"tasks"/(
                "phase_a_"+split+".jsonl")
            checked=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(checked,rows)

    def test_structured_proposals_accept_explicit_empty_artifact(self):
        art={"kind":"none","code":"","valid_examples":[],
             "invalid_examples":[]}
        self.assertIn("artifact",PROPOSAL_SCHEMA["required"])
        validated=validate("proposal",{
            "approach":"[S1] 2+2=4","artifact":art,
            "claims":[{"id":"c1","statement":"2+2=4"}],
            "hypotheses":[],"experiments":[]})
        self.assertEqual(validated["artifact"],art)

    def test_quick_full_pairing_bootstraps_by_task_kind(self):
        with TemporaryDirectory() as path:
            quick=Path(path)/"quick";full=Path(path)/"full"
            quick.mkdir();full.mkdir()
            for directory,correct in ((quick,[0,1]),(full,[1,1])):
                with (directory/"results.jsonl").open("w") as out:
                    for i,score in enumerate(correct):
                        out.write(json.dumps({
                            "system":"council","task_id":f"t{i}",
                            "kind":("numeric" if i==0 else "symbolic"),
                            "correct":score,"verified":0,
                            "false_verified":0})+"\n")
            report=paired_mode_comparison(quick,full)
            self.assertEqual(report["overall"]["paired_tasks"],2)
            self.assertAlmostEqual(
                report["overall"]["full_minus_quick_ci"][0],.5)
            self.assertEqual(report["by_kind"]["numeric"]["paired_tasks"],1)


class QuotaTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_token_bucket_shared_across_models(self):
        import time
        q=QuotaScheduler(default_rate=120,default_burst=2)
        q.configure("Groq","a",rate_per_minute=120,burst=2,
                    tokens_per_minute=1000)
        q.configure("Groq","b",rate_per_minute=120,burst=2,
                    tokens_per_minute=1000)
        await q.acquire("Groq","a",deadline=time.monotonic()+1,
                        expected_tokens=900)
        with self.assertRaises(QuotaContention):
            await q.acquire("Groq","b",deadline=time.monotonic()+.02,
                            expected_tokens=900)
        with self.assertRaises(QuotaContention):
            await q.acquire("Groq","b",deadline=time.monotonic()+.02,
                            expected_tokens=1001)


class HiddenCodeSandboxTests(unittest.TestCase):
    def test_python_source_extracted_without_exec(self):
        source="Here is the answer:\n"+chr(96)*3+"python\ndef f(xs):\n    return sum(xs)\n"+chr(96)*3
        self.assertEqual(extract_function_source(source),
                         "def f(xs):\n    return sum(xs)")
        self.assertIsNone(extract_function_source("The result is 13"))

    def test_hidden_examples_only_run_with_bwrap_and_are_not_selection_oracle(self):
        from council.verify.sandbox import SandboxResult
        cases={"cases":[{"input":[1,2],"expected":3},
                        {"input":[],"expected":0}]}
        source="def f(xs):\n    return sum(xs)"
        with patch("eval.code_tasks.available",return_value=False), \
             patch("eval.code_tasks.run_python") as execute:
            self.assertEqual(hidden_case_outcome(source,cases),"unavailable")
            execute.assert_not_called()
        with patch("eval.code_tasks.available",return_value=True), \
             patch("eval.code_tasks.run_python",
                   return_value=SandboxResult("pass","sandbox completed")) as execute:
            self.assertEqual(hidden_case_outcome(source,cases),"pass")
            submitted=execute.call_args.args[0]
            self.assertIn("def f(xs):",submitted)
            self.assertIn("__council_cases",submitted)
            self.assertIn("expected",submitted)
        with patch("eval.code_tasks.available",return_value=True), \
             patch("eval.code_tasks.run_python") as execute:
            self.assertEqual(hidden_case_outcome("not executable",cases),
                             "no_code")
            execute.assert_not_called()


class QuoteTraceTests(unittest.TestCase):
    def test_rejected_rfc_quote_is_logged_and_cannot_verify(self):
        dropped=[]
        result=normalize_topic_judgment(
            "full_uniqueness",
            {"section":"3.1","truncated":False,
             "excerpt":"The adversary outputs a public key."},
            [{"id":"p1:c1","statement":"Full uniqueness"}],
            {"best_version_id":"p1:c1",
             "versions":[{"id":"p1:c1","status":"matches",
                          "reference_quote":"Some invented reference text",
                          "reason":"looks right"}]},
            on_quote_rejected=lambda **kw:dropped.append(kw))
        self.assertIsNone(result["best_version_id"])
        self.assertEqual(result["versions"][0]["status"],"incomplete")
        self.assertEqual(dropped[0]["version"],"p1:c1")


if __name__=="__main__":
    unittest.main()

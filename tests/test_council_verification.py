"""Offline verification, source, quota, and sandbox regressions."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from council.quota import QuotaScheduler, QuotaContention
from council.translate import plan, translation_independent
from council.verify.mutation import numeric_mutants, code_mutants, assess
from council.verify.ladder import verify
from council.verify.source import PaperIndex
from council.verify.sandbox import available, run_python
from council.extract import validate_anchor, raw_text, final_number
from council.judge import enforce_verdict
from council.models import Claim, ClaimLedger

class ScopedChecks(unittest.TestCase):
    def test_claim_kind(self):
        self.assertEqual(plan("c",1,"universal",scope="every x").check_kind,
                         "formal_proof_or_counterexample")
        self.assertFalse(translation_independent("glm",{"glm"},high_stakes=False))
        self.assertTrue(translation_independent("glm",{"command","nemotron"},high_stakes=True))
    def test_arithmetic(self):
        p=plan("c",1,"arithmetic",scope="32*7")
        self.assertEqual(verify(p,{"expression":"32*7","expected":224}).outcome,"pass")
        self.assertEqual(verify(p,{"expression":"32*7","expected":225}).outcome,"fail")
    def test_research_not_certified(self):
        self.assertEqual(verify(plan("c",1,"novelty",scope="not in papers"),{}).outcome,
                         "unresolved")
    def test_mutations(self):
        self.assertIn("16",numeric_mutants("15"))
        self.assertTrue(code_mutants("x=3\ny=x+2"))
        self.assertFalse(assess(lambda _:"pass","original",["mutant"]).discriminating)
    def test_local_corpus_scoping(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=PaperIndex(Path(tmp)/"papers.db")
            db.add("a","A paper","The scheme is a conjecture.",license="CC-BY")
            self.assertTrue(db.quote("a","a conjecture").found)
            self.assertEqual(db.quote("a","a conjecture").semantic_entailment,"unchecked")
            self.assertFalse(db.quote("a","proven secure").found)
            db.close()
    def test_quantifier_preservation(self):
        span="For every adversary there exists a simulator."
        self.assertEqual(validate_anchor(span,span,span).source_span,span)
        with self.assertRaises(ValueError):
            validate_anchor(span,"A simulator exists",span)
    def test_final_number_handles_unicode_spaces_and_false_positives(self):
        self.assertEqual(final_number("Calculation:\n12\u202f×\u202f13\u202f=\u202f156"),"156")
        self.assertEqual(final_number("Intermediate: 130\nAnswer: **156**"),"156")
        self.assertEqual(final_number("The document mentions 156, but not as the final answer."),None)
        self.assertEqual(final_number("Answer: 155"),"155")

    def test_raw_reasoning(self):
        self.assertEqual(raw_text({"choices":[{"message":{"content":"",
                           "reasoning_content":"raw"}}]}),"raw")
    def test_judge_blocks_unproven(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("c",1,"unproven","nemotron"))
        verdict=enforce_verdict({"status":"answer","answer":"yes"},ledger)
        self.assertEqual(verdict["status"],"unresolved")
    def test_sandbox_fail_closed(self):
        result=run_python("print('test')")
        self.assertIn(result.outcome,("error","pass"))
        if not available():
            self.assertIn("NOT executed",result.detail)

    def test_sandbox_mounts_are_isolated(self):
        fake=SimpleNamespace(returncode=0,stdout='{"pass":true}',stderr="")
        with patch("council.verify.sandbox.available",return_value=True), \
             patch("council.verify.sandbox.subprocess.run",return_value=fake) as execute:
            output=run_python("print('sandbox')")
        self.assertEqual(output.outcome,"pass")
        command=execute.call_args.args[0]
        self.assertIn("--unshare-all",command)
        self.assertIn("--clearenv",command)
        self.assertIn("--bind",command)
        work_at=command.index("/work")
        self.assertEqual(command[work_at-2],"--bind")
        self.assertIn("--ro-bind",command)
        self.assertNotIn("/home",command)

class QuotaTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_account_daily_cap(self):
        q=QuotaScheduler()
        q.configure("Groq","m",rate_per_minute=600,burst=2)
        q.shared_daily["Groq"]=1
        await q.acquire("Groq","m",deadline=time.monotonic()+2)
        with self.assertRaises(QuotaContention):
            await q.acquire("Groq","m",deadline=time.monotonic()+2)
    async def test_retry_after(self):
        q=QuotaScheduler()
        q.configure("Groq","m",rate_per_minute=600,burst=2)
        q.observe("Groq","m",{"Retry-After":"30"})
        with self.assertRaises(QuotaContention):
            await q.acquire("Groq","m",deadline=time.monotonic()+1)
    async def test_circuit_breaker(self):
        q=QuotaScheduler()
        q.configure("Groq","m",rate_per_minute=600,burst=2)
        for _ in range(3):
            q.failure("Groq","m",kind="server")
        with self.assertRaises(QuotaContention):
            await q.acquire("Groq","m",deadline=time.monotonic()+2)

if __name__=="__main__":
    unittest.main()

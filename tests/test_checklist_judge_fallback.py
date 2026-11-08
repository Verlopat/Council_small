"""Regression coverage for judge failure cause and same-family fallback events."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from council.judge import judge_failure, enforce_verdict
from council.models import Claim, ClaimLedger
from council.transport import FamilyTransport
from council.budget import RunBudget
from router_errors import CandidateError

class FallbackRouter:
    def expand(self, candidate, seen):
        return [candidate]
    def generate(self, candidate, prompt, **kwargs):
        if candidate.provider == "Z.ai":
            raise CandidateError("Simulated server problem", kind="server")
        return '{"ok":true}'

class JudgeAndFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_judge_cause_survives_blocking_claims(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("open-claim",1,"Unproved proposal","gpt-oss"))
        outcome=judge_failure(ledger)
        self.assertEqual(outcome["cause"],"judge_error")
        self.assertEqual(outcome["status"],"unresolved")
        self.assertIn("open-claim",outcome["blocking"])
        for cause in ("composition_failure","deadline","quota_contention"):
            result=enforce_verdict({"status":"answer","answer":"yes","cause":cause},ledger)
            self.assertEqual(result["cause"],cause)
            self.assertIsNone(result["answer"])

    async def test_fallback_selected_records_actual_endpoint(self):
        records=[]
        def record(event,**kw):
            records.append((event,kw))
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{
                 "ZAI_API_KEY":"dummy","CLOUDFLARE_API_TOKEN":"dummy",
                 "COUNCIL_HARD_DEADLINE":"0"}):
                transport=FamilyTransport(
                    record=record,health_file=Path(folder)/"health.json")
                transport.router=FallbackRouter()
                response=await transport.complete("glm","Original question",
                    RunBudget.start(30,4),role="proposal",synthesis=True)
        fallbacks=[data for event,data in records if event=="fallback_selected"]
        self.assertEqual(len(fallbacks),1)
        self.assertEqual(fallbacks[0]["provider"],"Cloudflare")
        self.assertEqual(fallbacks[0]["model"],"@cf/zai-org/glm-4.7-flash")
        self.assertTrue(fallbacks[0]["skipped"])
        self.assertEqual(response.provider,"Cloudflare")

if __name__=="__main__":
    unittest.main()

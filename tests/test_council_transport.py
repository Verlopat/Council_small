"""No real API requests; ensure identity, family fallback and free-mode gating."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from council.budget import RunBudget
from council.transport import FamilyTransport, FamilyUnavailable
from router_errors import CandidateError

class DummyRouter:
    def __init__(self):
        self.calls = []

    def expand(self, candidate, seen):
        return [candidate]

    def generate(self, candidate, message, *, probe=False, request_timeout=None,
                 max_output_tokens=None):
        self.calls.append((candidate.provider, candidate.model, message))
        if candidate.provider == "Z.ai":
            raise CandidateError("simulated server failure", kind="server")
        return "response from " + candidate.provider

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_glm_fallback_remains_in_same_family(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {
                    "ZAI_API_KEY": "mock-zai",
                    "CLOUDFLARE_API_TOKEN": "mock-cloudflare"}):
                t = FamilyTransport(health_file=Path(folder) / "health.json")
                fake = DummyRouter()
                t.router = fake
                response = await t.complete("glm", "Original prompt", RunBudget.start(30, 4),
                                            role="audit", synthesis=True)
            self.assertEqual(response.family, "glm")
            self.assertEqual(response.provider, "Cloudflare")
            self.assertEqual([x[0] for x in fake.calls], ["Z.ai", "Cloudflare"])
            self.assertTrue(all(x[2] == "Original prompt" for x in fake.calls))

    async def test_cohere_requires_confirmed_trial_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"COHERE_API_KEY":"dummy",
                                         "COHERE_TRIAL_CONFIRMED":"0"}):
                t = FamilyTransport(health_file=Path(folder) / "health.json")
                t.router = DummyRouter()
                with self.assertRaises(FamilyUnavailable):
                    await t.complete("command", "Prompt", RunBudget.start(10, 1),
                                     role="proposal")
                self.assertEqual(t.router.calls, [])

    async def test_structured_output_token_budget_is_forwarded(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"GROQ_API_KEY":"mock"}):
                t = FamilyTransport(health_file=Path(folder) / "health.json")
                observed = []
                fake = DummyRouter()
                real_generate = fake.generate
                def record_generate(candidate, message, **kwargs):
                    observed.append(kwargs.get("max_output_tokens"))
                    return real_generate(candidate, message, **kwargs)
                fake.generate = record_generate
                t.router = fake
                await t.complete("gpt-oss", "Prompt", RunBudget.start(30, 4),
                                 role="proposal")
                self.assertEqual(observed, [1800])

if __name__ == "__main__":
    unittest.main()

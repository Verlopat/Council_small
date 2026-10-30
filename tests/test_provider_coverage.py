"""Local provider coverage is honest about free-tier and family assignment."""
import io
from contextlib import redirect_stdout
import json
import unittest
from council.providers import provider_coverage
from council.cli import main

class CoverageTests(unittest.TestCase):
    def test_all_eight_no_nvidia_and_no_real_calls(self):
        report=provider_coverage(env={},active_families={"gemini","glm"})
        self.assertEqual(report["provider_count"],8)
        self.assertEqual(report["family_count"],7)
        self.assertNotIn("NVIDIA NIM",report["providers"])
        self.assertTrue(report["providers"]["Cloudflare"]["in_run"])
        self.assertFalse(report["providers"]["Groq"]["in_run"])
        self.assertEqual(report["providers"]["Gemini"]["status"],"not_configured")
        self.assertTrue(all(not x["live_checked"] for x in report["providers"].values()))
    def test_free_confirmation_is_not_key_presence(self):
        env={"COHERE_API_KEY":"fake", "OLLAMA_API_KEY":"fake",
             "CLOUDFLARE_API_TOKEN":"fake"}
        report=provider_coverage(env=env)
        self.assertEqual(report["providers"]["Cohere"]["status"],
                         "free_confirmation_required")
        self.assertEqual(report["providers"]["Ollama Cloud"]["status"],
                         "free_confirmation_required")
        self.assertEqual(report["providers"]["Cloudflare"]["status"],"not_configured")
        env.update({"COHERE_TRIAL_CONFIRMED":"1","OLLAMA_FREE_CONFIRMED":"1",
                    "CLOUDFLARE_ACCOUNT_ID":"fake-account"})
        report=provider_coverage(env=env)
        for provider in ("Cohere","Ollama Cloud","Cloudflare"):
            self.assertEqual(report["providers"][provider]["status"],
                             "configured_unverified")
    def test_cli_reports_eight_without_a_question(self):
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(["--provider-report","--mode","full"])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(output.getvalue())["provider_count"],8)
    def test_family_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            provider_coverage(env={},active_families={"imaginary"})

if __name__=="__main__":
    unittest.main()

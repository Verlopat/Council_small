"""Hard-stop inference backend is optional, bounded and selected explicitly."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from council.budget import RunBudget
from council.transport import FamilyTransport
from council.process_infer import generate

class FakeRouter:
    def expand(self, candidate, seen):
        return [candidate]
    def generate(self, *args, **kwargs):
        raise AssertionError("Thread provider path used while hard-stop enabled")

class ProcessTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_opt_in_process_is_used_instead_of_thread_router(self):
        with TemporaryDirectory() as path, patch.dict(os.environ,{
            "GROQ_API_KEY":"dummy-only", "COUNCIL_HARD_DEADLINE":"1"}), \
             patch("council.process_infer.generate",return_value=("42",None)) as process:
            transport=FamilyTransport(health_file=Path(path)/"health.json")
            transport.router=FakeRouter()
            result=await transport.complete("gpt-oss","Prompt",
                           RunBudget.start(12,0),role="proposal",synthesis=True)
            self.assertEqual(result.text,"42")
            process.assert_called_once()
            self.assertEqual(process.call_args.kwargs["max_tokens"],1800)
    async def test_hard_request_rejects_invalid_timeout(self):
        with self.assertRaises(ValueError):
            generate("Groq","model","question",system_text=None,timeout=0)

if __name__=="__main__":
    unittest.main()

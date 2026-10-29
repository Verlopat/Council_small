"""Raw replay uses role+family+prompt hash; no original APIs are queried."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from council.replay import ReplayTransport, ResumeTransport
from council.transport import FamilyUnavailable

class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_response_and_missing_prompt(self):
        message="MODEL DATA"
        digest=hashlib.sha256(message.encode()).hexdigest()
        events=[{"event":"model_call_started","payload":{
                    "role":"proposal","family":"gpt-oss","prompt_hash":digest}},
                {"event":"model_call_succeeded","payload":{
                    "role":"proposal","family":"gpt-oss","provider":"Groq",
                    "model":"openai/gpt-oss-120b","prompt_hash":digest,
                    "response":'{"approach":"demo"}',"seconds":1.5}}]
        replay=ReplayTransport(events)
        response=await replay.complete("gpt-oss",message,None,role="proposal")
        self.assertEqual(response.provider,"Groq")
        self.assertEqual(response.text,'{"approach":"demo"}')
        with self.assertRaises(FamilyUnavailable):
            await replay.complete("gpt-oss","a different prompt",None,role="proposal")

    async def test_original_missing_provider_preserved(self):
        replay=ReplayTransport([{"event":"role_unavailable","payload":{
            "role":"proposal","family":"command","failures":["trial disabled"]}}])
        with self.assertRaises(FamilyUnavailable):
            await replay.complete("command","a",None,role="proposal")

if __name__=="__main__":
    unittest.main()

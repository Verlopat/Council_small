"""Council-specific OpenRouter reasoning controls; no model API calls."""
import unittest
from unittest.mock import patch

from model_router import Candidate, Router
from router_errors import CandidateError


MODEL="nvidia/nemotron-3-ultra-550b-a55b:free"


class RoutingReasoningTests(unittest.TestCase):
    def _generate(self, model=MODEL, system_text="SYSTEM ROLE: REVIEW"):
        captured=[]
        def fake_api_call(method,url,*,key=None,headers=None,payload=None,timeout=22):
            captured.append((url,payload))
            return {"choices":[{"finish_reason":"stop",
                                "message":{"content":"{}"}}]}
        with patch.dict("os.environ",{
            "OPENROUTER_API_KEY":"offline_dummy_test",
            "COUNCIL_NEMOTRON_REASONING_EFFORT":"low"}):
            with patch("model_router.api_call",side_effect=fake_api_call):
                text=Router().generate(
                    Candidate("OpenRouter",model),
                    "Return a short JSON object.",system_text=system_text,
                    max_output_tokens=8000)
        self.assertEqual(text,"{}")
        self.assertEqual(len(captured),1)
        return captured[0][1]

    def test_nemotron_council_uses_low_reasoning(self):
        request=self._generate()
        self.assertEqual(request["reasoning"],{"effort":"low"})
        self.assertEqual(request["max_tokens"],8000)
        self.assertEqual(request["messages"][0]["role"],"system")

    def test_direct_nemotron_keeps_provider_default(self):
        request=self._generate(system_text=None)
        self.assertNotIn("reasoning",request)

    def test_unrelated_openrouter_model_has_no_reasoning_override(self):
        request=self._generate(model="some/other-free-model")
        self.assertNotIn("reasoning",request)

    def test_invalid_reasoning_option_rejected_before_network(self):
        with patch.dict("os.environ",{
            "OPENROUTER_API_KEY":"offline_dummy_test",
            "COUNCIL_NEMOTRON_REASONING_EFFORT":"nonsense"}):
            with patch("model_router.api_call") as api:
                with self.assertRaises(CandidateError):
                    Router().generate(Candidate("OpenRouter",MODEL),"{}",
                                      system_text="SYSTEM ROLE: REVIEW",
                                      max_output_tokens=8000)
                api.assert_not_called()


if __name__=="__main__":
    unittest.main()

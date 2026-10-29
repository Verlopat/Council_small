"""End-to-end Council tests, using mock responses only (zero API quota)."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from council.budget import RunBudget
from council.events import EventStore
from council.transport import CallResult, FamilyUnavailable
from council.workflow import CouncilRunner

class FakeTransport:
    def __init__(self, missing=()):
        self.calls = []
        self.missing = set(missing)

    async def complete(self, family, message, budget, *, role, synthesis=False):
        self.calls.append((family, role, message, synthesis))
        if family in self.missing:
            raise FamilyUnavailable(family, ["missing mocked provider"])
        if role == "proposal":
            content = {"approach": "Approach by " + family,
                       "claims": [{"id":"c1","statement":"Unproven theorem by " + family,
                                   "limitations":["no proof"]}],
                       "hypotheses":["Hypothesis " + family],
                       "experiments":["Experiment " + family]}
        elif role == "review":
            content = {"objections":[{"claim_id":"c1","issue":"Proof gap",
                                      "consequence":"The theorem may not hold",
                                      "suggested_check":"Construct a counterexample"}]}
        elif role == "revision":
            content = {"revised_approach":"Revised " + family,
                       "revised_claims":[{"claim_id":"p1:c1", "statement":"Revised claim"}],
                       "responses":[{"objection_id":"o1","disposition":"partial",
                                      "explanation":"More tests needed"}]}
        elif role == "synthesis":
            content = {"proposed_approach":"Combined conjectural protocol",
                       "supported_findings":["Made-up verified-sounding claim"],
                       "hypotheses":["Potential construction"],
                       "unresolved_objections":["Missing reduction"],
                       "proof_obligations":["Prove IND-CPA"],
                       "proposed_experiments":["Write an adversarial simulator"],
                       "next_actions":["Specify the game"],"completion_status":"partial"}
        else:
            content = {"issues":["The reduction has not been proved"],
                       "suggested_checks":["Implement a reference game"]}
        return CallResult(family, family + "-provider", family + "-model",
                          json.dumps(content), 0.001, "hash")

class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_flow_sealed_review_revision_synthesis_audit(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d), "run") as events:
                transport = FakeTransport()
                result = await CouncilRunner(
                    transport, events, RunBudget.start(100, reserve=10)
                ).run("Construct a verifiable lattice PRF", mode="research")
                self.assertEqual(len(result["proposals"]), 3)
                self.assertEqual(len(result["objections"]), 3)
                self.assertEqual(result["research_result"]["completion_status"], "partial")
                self.assertEqual(result["research_result"]["supported_findings"], [])
                self.assertIn("Made-up verified-sounding claim",
                              result["research_result"]["hypotheses"])
                self.assertIn("The reduction has not been proved",
                              result["research_result"]["unresolved_objections"])
                roles = [role for family,role,_,_ in transport.calls]
                self.assertEqual(roles[:3], ["proposal"]*3)
                self.assertEqual(roles[-2:], ["synthesis","audit"])
                self.assertTrue(all(fam != "gemini" for fam,role,_,_ in
                                    transport.calls if role != "synthesis"))
                events_seen = [entry["event"] for entry in events.replay()]
                self.assertIn("claim_revised", events_seen)
                self.assertEqual(events_seen[-1], "run_finished")

    async def test_quick_uses_one_proposal_and_synthesis(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d), "quick") as events:
                t = FakeTransport()
                result = await CouncilRunner(t, events, RunBudget.start(40, reserve=10)).run(
                    "What would we investigate?", mode="quick")
                self.assertEqual([x[1] for x in t.calls], ["proposal", "synthesis"])
                self.assertEqual(len(result["proposals"]), 1)

    async def test_missing_providers_return_deterministic_unresolved(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d), "none") as events:
                t = FakeTransport(missing=("gpt-oss", "command", "nemotron"))
                result = await CouncilRunner(t, events, RunBudget.start(20)).run(
                    "Investigate", mode="research")
                self.assertEqual(result["research_result"]["completion_status"], "unresolved")
                self.assertEqual(result["proposals"], [])
                self.assertEqual([x[1] for x in t.calls], ["proposal"]*3)

if __name__ == "__main__":
    unittest.main()

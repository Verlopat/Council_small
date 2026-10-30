"""Integration check: a second debate round requires fresh checked repair evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from council.full import FullCouncilRunner
from council.budget import RunBudget
from council.events import EventStore
from council.transport import CallResult

class RepairTransport:
    def __init__(self):
        self.calls = []

    async def complete(self, family, message, budget, *, role, synthesis=False):
        data = json.loads(message.split("DATA_JSON:\n", 1)[-1])
        self.calls.append((family,role))
        if role == "proposal":
            body = {"answer":"2+2=5","approach":"2+2=5",
                    "claims":[{"id":"c1","statement":"2+2=5","source_span":"2+2=5"}],
                    "hypotheses":[],"experiments":[]}
        elif role == "extract":
            body = {"claims":[]}
        elif role == "review":
            claim_id = data["claims"][0]["id"]
            body = {"objections":[{"claim_id":claim_id, "issue":"Arithmetic mismatch",
                    "consequence":"Unjustified", "suggested_check":"Recompute 2+2"}]}
        elif role == "revision":
            body = {"revised_approach":"2+2=5", "responses":[], "revised_claims":[]}
        elif role == "translate":
            if data["claim_id"].endswith(":repair"):
                body={"claim_kind":"arithmetic","scope":"2+2=4",
                      "artifact":{"expression":"2+2","expected":4}}
            else:
                body={"claim_kind":"novelty","scope":"not established",
                      "artifact":{}}
        elif role == "hunter":
            body={"found":False,"tried":["none"]}
        elif role == "repair":
            body={"revised_statement":"2+2=4","assumptions":[]}
        elif role == "coverage":
            body={"missing_requirements":[]}
        elif role == "judge":
            body={"status":"unresolved","partial_answer":"2+2=4",
                  "blocking":[],"basis":[]}
        elif role == "audit":
            body={"issues":[],"suggested_checks":[]}
        else:
            body={}
        return CallResult(family, family+"-provider", family+"-model",
                          json.dumps(body),0.001,"hash")

class FollowupTests(unittest.IsolatedAsyncioTestCase):
    async def test_checked_repair_opens_one_followup_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            with EventStore(Path(tmp),"repair") as events:
                t=RepairTransport()
                runner=FullCouncilRunner(t,events,RunBudget.start(90,12),
                                         max_claims=3,hunter_cap=1,
                                         enable_coverage=False)
                result=await runner.run("Check this arithmetic",mode="full")
                kinds=[ev["event"] for ev in events.replay()]
                self.assertIn("repair_claim_proposed",kinds)
                self.assertIn("evidence_gated_followup_round",kinds)
                self.assertTrue(any(c["id"].endswith(":repair") for c in result["claims"]))

if __name__=="__main__":
    unittest.main()

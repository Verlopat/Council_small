"""Offline full P0-P6 integration, including scoped arithmetic and blindness."""
import json
from pathlib import Path
import tempfile
import unittest
from council.full import FullCouncilRunner, QuickCouncilRunner
from council.budget import RunBudget
from council.events import EventStore
from council.transport import CallResult

class FakeFullTransport:
    def __init__(self,anchored=True):
        self.calls=[]
        self.anchored=anchored
    async def complete(self,family,message,budget,*,role,synthesis=False):
        self.calls.append((family,role,message))
        if role=="proposal":
            answer="2+2=4" if self.anchored else "Consider an unproven theorem"
            body={"answer":answer,"approach":answer,
                  "claims":[{"id":"c1","statement":"2+2=4",
                             "source_span":"2+2=4" if self.anchored else "missing"}],
                  "hypotheses":[],"experiments":[]}
        elif role=="extract":
            body={"claims":[]}
        elif role=="translate":
            body={"claim_kind":"arithmetic","scope":"2+2=4",
                  "artifact":{"expression":"2+2","expected":4}}
        elif role=="coverage":
            body={"missing_requirements":[]}
        elif role=="hunter":
            body={"found":False,"tried":["sample"]}
        elif role=="judge":
            body={"status":"answer","answer":"4",
                  "partial_answer":"4","blocking":[],"basis":[]}
        elif role=="audit":
            body={"issues":[],"suggested_checks":[]}
        else:
            body={}
        return CallResult(family,family+"-provider",family+"-model",
                          json.dumps(body),0.01,"hash")

class FullModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_arithmetic_scoped_support(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"f") as events:
                transport=FakeFullTransport()
                runner=FullCouncilRunner(transport,events,RunBudget.start(100,15))
                result=await runner.run("Check the equality",mode="full")
                self.assertEqual([x[1] for x in transport.calls[:3]],["proposal"]*3)
                self.assertEqual(len(result["proposals"]),3)
                self.assertTrue(result["evidence"])
                self.assertTrue(result["research_result"]["supported_findings"])
                self.assertEqual(result["verdict"]["status"],"answer")
                self.assertEqual(events.replay()[-1]["event"],"run_finished")
    async def test_quick_checks_before_judging(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"quick") as events:
                t=FakeFullTransport()
                result=await QuickCouncilRunner(
                    t,events,RunBudget.start(80,10)).run("Check equality")
                self.assertEqual([x[1] for x in t.calls],
                                 ["proposal","translate","judge"])
                self.assertTrue(result["research_result"]["supported_findings"])
                self.assertEqual(result["verdict"]["status"],"answer")

    async def test_no_anchor_means_no_certification(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"f") as events:
                runner=FullCouncilRunner(FakeFullTransport(False),events,RunBudget.start(100,15))
                result=await runner.run("Does the theorem hold?",mode="full")
                self.assertFalse(result["research_result"]["supported_findings"])
                self.assertEqual(result["verdict"]["status"],"unresolved")

if __name__=="__main__":
    unittest.main()

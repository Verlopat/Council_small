"""Four-solver mode degrades honestly when no independent auditor is available."""
import json
import tempfile
from pathlib import Path
import unittest

from council.budget import RunBudget
from council.config import load_config
from council.events import EventStore
from council.full import FullCouncilRunner
from council.transport import CallResult

class FourFamilyFake:
    def __init__(self):
        self.roles=[]
    async def complete(self,family,message,budget,*,role,synthesis=False):
        self.roles.append((family,role))
        if role=="proposal":
            body={"answer":"2+2=4","approach":"2+2=4",
                  "claims":[{"id":"c1","statement":"2+2=4",
                             "source_span":"2+2=4"}],
                  "hypotheses":[],"experiments":[]}
        elif role=="extract": body={"claims":[]}
        elif role=="review": body={"objections":[]}
        elif role=="translate":
            body={"claim_kind":"arithmetic","scope":"2+2=4",
                  "artifact":{"expression":"2+2","expected":4}}
        elif role=="judge":
            body={"status":"answer","answer":"4","partial_answer":"4",
                  "blocking":[],"basis":[]}
        elif role=="audit":
            raise AssertionError("No model may be an undeclared auditor")
        else:
            body={}
        return CallResult(family,family+"-mock",family+"-mock",
                          json.dumps(body),0.01,"hash")

class FourSolvers(unittest.IsolatedAsyncioTestCase):
    async def test_explicitly_missing_auditor_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            filename=Path(d)/"config.yaml"
            filename.write_text("""
mode: full
deadline_seconds: 90
solvers: [gpt-oss, command, nemotron, gemma]
translator: glm
judge: gemini
auditor: null
""")
            cfg=load_config(filename)
            self.assertIsNone(cfg.assignment.auditor)
            with EventStore(Path(d),"four") as events:
                t=FourFamilyFake()
                runner=FullCouncilRunner(t,events,RunBudget.start(90,15),
                    solvers=cfg.solvers,auditor_family=cfg.auditor,
                    max_claims=4,hunter_cap=0,enable_coverage=False,
                    enable_repairs=False)
                result=await runner.run("Check this",mode="full")
            self.assertEqual([role for _,role in t.roles].count("proposal"),4)
            self.assertEqual([role for _,role in t.roles].count("audit"),0)
            self.assertIn("Independent auditor not assigned",
                          result["research_result"]["limitations"])

if __name__=="__main__":
    unittest.main()

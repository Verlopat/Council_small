"""Configured solver strategies must reach first-round prompts and metadata."""
import json
import tempfile
from pathlib import Path
import unittest

from council.budget import RunBudget
from council.config import load_config
from council.events import EventStore
from council.full import FullCouncilRunner
from council.transport import CallResult

class StrategyFake:
    def __init__(self):
        self.first={}
    async def complete(self,family,message,budget,*,role,synthesis=False):
        data=json.loads(message.split("DATA_JSON:\n",1)[1])
        if role=="proposal":
            self.first[family]=data["strategy"]
            body={"answer":"2+2=4","approach":"2+2=4",
                  "claims":[{"id":"c1","statement":"2+2=4",
                            "source_span":"2+2=4"}],
                  "hypotheses":[],"experiments":[]}
        elif role=="translate":
            body={"claim_kind":"arithmetic","scope":"2+2=4",
                  "artifact":{"expression":"2+2","expected":4}}
        elif role=="judge":
            body={"status":"answer","answer":"4","partial_answer":"4",
                  "blocking":[],"basis":[]}
        elif role=="extract": body={"claims":[]}
        elif role=="review": body={"objections":[]}
        elif role=="audit": body={"issues":[],"suggested_checks":[]}
        else: body={}
        return CallResult(family,family+"-provider",family+"-model",
                          json.dumps(body),0.01,"hash")

class Strategies(unittest.IsolatedAsyncioTestCase):
    async def test_three_distinct_strategy_directives_survive_execution(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/"config.yaml"
            cfg.write_text("""
mode: full
deadline_seconds: 90
solvers:
 - {family: gpt-oss, strategy: direct}
 - {family: command, strategy: code}
 - {family: nemotron, strategy: decompose}
""")
            loaded=load_config(cfg)
            with EventStore(Path(d),"strategies") as events:
                t=StrategyFake()
                runner=FullCouncilRunner(t,events,RunBudget.start(90,12),
                     solver_strategies=loaded.solver_strategies,
                     hunter_cap=0,enable_coverage=False,enable_repairs=False)
                await runner.run("What is 2+2?",mode="full")
                start=next(e for e in events.replay() if e["event"]=="run_started")
            self.assertEqual(t.first,{"gpt-oss":"direct","command":"code",
                                      "nemotron":"decompose"})
            self.assertEqual(start["payload"]["solver_strategies"],t.first)
    async def test_unknown_strategy_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/"bad.yaml"
            cfg.write_text("""
mode: full
deadline_seconds: 90
solvers:
 - {family: gpt-oss, strategy: imaginary}
""")
            with self.assertRaises(ValueError):
                load_config(cfg)

if __name__=="__main__":
    unittest.main()

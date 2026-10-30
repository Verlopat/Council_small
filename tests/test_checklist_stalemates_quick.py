"""Check named stalemate outcomes and quick-mode family configuration."""
import json
from pathlib import Path
import tempfile
import unittest

from council.bus import MessageBus, MessageCap
from council.moderator import Moderator
from council.protocol import Message, Act
from council.models import Claim, ClaimLedger
from council.full import FullCouncilRunner, QuickCouncilRunner
from council.config import load_config
from council.budget import RunBudget
from council.events import EventStore
from council.transport import CallResult

def msg(identity,act,text):
    return Message(identity,"c",act,"author","gpt-oss",text)

class StalemateTests(unittest.TestCase):
    def test_bus_accepts_only_four_stalemate_causes(self):
        bus=MessageBus()
        with self.assertRaises(ValueError):
            bus.close("c","model_agreement")
        bus.close("c","no_evidence_possible")
        self.assertEqual(bus.stalemates()["c"],"no_evidence_possible")

    def test_duplicate_twice_closes_thread(self):
        bus=MessageBus()
        self.assertEqual(bus.deliver(msg("1",Act.ASK,"What is the witness?")),"accepted")
        self.assertEqual(bus.deliver(msg("2",Act.ASK,"What is the witness?")),"duplicate")
        self.assertEqual(bus.deliver(msg("3",Act.ASK,"What is the witness?")),"duplicate")
        self.assertEqual(bus.stalemates()["c"],"dedupe_dropped")

    def test_repair_from_closed_thread_consumes_cap_without_reopening(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("c",1,"Unproved","gpt-oss"))
        moderator=Moderator(ledger)
        moderator.bus.close("c","no_evidence_possible")
        self.assertTrue(moderator.authorize_repair_from_stalemate("c","nemotron"))
        self.assertFalse(moderator.authorize_repair_from_stalemate("c","nemotron"))
        self.assertEqual(moderator.bus.stalemates()["c"],"no_evidence_possible")
        self.assertEqual(moderator.bus.threads["c"].repairs,1)

    def test_moderator_abstain_and_cap_hit(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("c",1,"Open","gpt-oss"))
        audit=[]
        moderator=Moderator(ledger,events=lambda kind,**kwargs:audit.append((kind,kwargs)))
        self.assertEqual(moderator.submit(msg("a",Act.ABSTAIN,"Cannot advance")),"accepted")
        self.assertEqual(moderator.bus.stalemates()["c"],"agents_gave_up")
        self.assertTrue(any(kind=="stalemate" for kind,_ in audit))
        ledger2=ClaimLedger()
        ledger2.add_claim(Claim("c",1,"Open","gpt-oss"))
        mod2=Moderator(ledger2,bus=MessageBus(message_cap=1),
                       events=lambda kind,**kwargs:audit.append((kind,kwargs)))
        mod2.submit(msg("b",Act.ASK,"First"))
        with self.assertRaises(MessageCap):
            mod2.submit(msg("d",Act.ASK,"Second"))
        self.assertEqual(mod2.bus.stalemates()["c"],"cap_hit")

class QuickFake:
    def __init__(self):self.calls=[]
    async def complete(self,family,message,budget,*,role,synthesis=False):
        self.calls.append((family,role))
        if role=="proposal":
            body={"approach":"2+2=4","answer":"2+2=4",
                  "claims":[{"id":"c1","statement":"2+2=4",
                             "source_span":"2+2=4"}],"hypotheses":[],"experiments":[]}
        elif role=="translate":
            body={"claim_kind":"arithmetic","scope":"2+2=4",
                  "artifact":{"expression":"2+2","expected":4}}
        elif role=="judge":
            body={"status":"answer","answer":"4","partial_answer":"4",
                  "blocking":[],"basis":[]}
        else:
            body={}
        return CallResult(family,family+"-endpoint",family+"-model",
                          json.dumps(body),0.001,"digest")

class QuickConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_yaml_solver_controls_quick_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"council.yaml"
            path.write_text("""
mode: quick
deadline_seconds: 90
solvers:
  - {family: nemotron, strategy: decompose}
  - {family: gpt-oss, strategy: direct}
translator: glm
judge: gemini
auditor: gemma
""")
            cfg=load_config(path)
            fake=QuickFake()
            with EventStore(Path(folder),"quick") as events:
                runner=QuickCouncilRunner(
                    fake,events,RunBudget.start(90,15),
                    solver=cfg.solvers[0],
                    translator_family=cfg.translator,
                    judge_family=cfg.judge,
                    solver_strategies=cfg.solver_strategies)
                await runner.run("Compute 2+2")
            self.assertEqual(fake.calls[0],("nemotron","proposal"))
            self.assertEqual([role for _,role in fake.calls],
                             ["proposal","translate","judge"])

if __name__=="__main__":
    unittest.main()

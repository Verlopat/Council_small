"""Concurrent hunter inference, serial evidence/state commits."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from council.budget import RunBudget
from council.events import EventStore
from council.full import FullCouncilRunner
from council.models import Claim
from council.transport import CallResult

class SlowHunter:
    def __init__(self):
        self.active = 0
        self.peak = 0

    async def complete(self, family, message, budget, *, role, synthesis=False):
        assert role == "hunter"
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(.02)
        self.active -= 1
        payload=json.loads(message.split("DATA_JSON:\n",1)[1])
        return CallResult(family, "fake", family+"-mock",
                          json.dumps({"found":True,
                                      "counterexample":"Missing proof step in "+payload["claim_id"]}),
                          .02, "hash")

class ConcurrentHunterTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_overlap_but_thread_order_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"hunters") as events:
                transport=SlowHunter()
                runner=FullCouncilRunner(transport,events,RunBudget.start(80,10))
                a=Claim("p1:c1",1,"Unproved A","gpt-oss")
                b=Claim("p2:c1",1,"Unproved B","command")
                runner.ledger.add_claim(a)
                runner.ledger.add_claim(b)
                await runner._hunt_batch([(a,"nemotron",1),(b,"nemotron",1)])
                self.assertEqual(transport.peak,2)
                self.assertEqual(list(runner.moderator.bus.threads),["p1:c1","p2:c1"])
                logs=[ev["payload"]["claim_id"] for ev in events.replay()
                      if ev["event"]=="hunter_objection"]
                self.assertEqual(logs,["p1:c1","p2:c1"])

    async def test_judge_and_owner_families_never_hunt(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"reserved") as events:
                transport=SlowHunter()
                runner=FullCouncilRunner(transport,events,RunBudget.start(80,10))
                claim=Claim("c1",1,"Unproved","gpt-oss")
                runner.ledger.add_claim(claim)
                await runner._hunt_batch([(claim,"gemini",1),(claim,"gpt-oss",1),
                                          (claim,"gemma",1)])
                self.assertEqual(transport.peak,0)
                self.assertFalse(runner.moderator.bus.threads)

if __name__=="__main__":
    unittest.main()

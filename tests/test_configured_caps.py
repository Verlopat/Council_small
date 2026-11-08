"""Configured debate caps control the actual moderator and reject invalid limits."""
from pathlib import Path
import tempfile
import unittest

from council.budget import RunBudget
from council.config import load_config
from council.events import EventStore
from council.full import FullCouncilRunner

class ConfiguredCapsTests(unittest.TestCase):
    def test_yaml_limits_reach_message_bus(self):
        with tempfile.TemporaryDirectory() as d:
            config=Path(d)/"test.yaml"
            config.write_text("""
mode: full
deadline_seconds: 80
solvers: [gpt-oss, command, nemotron]
translator: glm
judge: gemini
auditor: gemma
caps:
  messages: 2
  verifier_calls: 1
  repairs: 1
  pair_exchanges: 2
""")
            cfg=load_config(config)
            self.assertEqual(cfg.caps["messages"],2)
            with EventStore(Path(d),"caps") as events:
                runner=FullCouncilRunner(None,events,RunBudget.start(40,5),
                                         caps=cfg.caps)
                bus=runner.moderator.bus
                self.assertEqual(bus.message_cap,2)
                self.assertEqual(bus.verifier_cap,1)
                self.assertEqual(bus.pair_cap,2)

    def test_invalid_caps_fail_before_calls(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"invalid") as events:
                with self.assertRaises(ValueError):
                    FullCouncilRunner(None,events,RunBudget.start(40,5),
                                      caps={"messages":0})
            config=Path(d)/"test.yaml"
            config.write_text("""
mode: full
deadline_seconds: 80
solvers: [gpt-oss, command, nemotron]
caps: {messages: 0}
""")
            with self.assertRaises(ValueError):
                load_config(config)

if __name__=="__main__":
    unittest.main()

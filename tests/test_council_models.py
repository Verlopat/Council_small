"""Offline invariant tests for versioned claims and research evidence."""
import tempfile
from pathlib import Path
import unittest

from council.models import Claim, ClaimLedger, ClaimStatus, Evidence, EvidenceKind
from council.families import FAMILIES, quorum, validate_assignment
from council.parse import parse_object, OutputError
from council.events import EventStore
from council.cache_key import response_cache_key
from council.verify.arithmetic import check, calculate

class ClaimTests(unittest.TestCase):
    def test_support_is_scoped_and_revision_invalidates(self):
        ledger = ClaimLedger()
        ledger.add_claim(Claim("c1", 1, "2+2=4", "gpt-oss"))
        ledger.attach(Evidence("e1", "c1", 1, EvidenceKind.TEST, "pass",
                               "2+2", "abc", independently_checked=True))
        self.assertEqual(ledger.claims["c1"].status, ClaimStatus.SUPPORTED)
        new = ledger.revise("c1", "2+2=5")
        self.assertEqual(new.version, 2)
        self.assertEqual(new.evidence_ids, [])
        self.assertEqual(new.status, ClaimStatus.PROPOSED)
        with self.assertRaises(ValueError):
            ledger.attach(Evidence("e2", "c1", 1, EvidenceKind.TEST, "pass",
                                   "outdated test", "abc", independently_checked=True))

    def test_unchecked_review_does_not_certify(self):
        ledger = ClaimLedger()
        ledger.add_claim(Claim("c", 1, "Claim under review", "command"))
        ledger.attach(Evidence("e", "c", 1, EvidenceKind.MODEL_REVIEW, "pass",
                               "opinion", "h", independently_checked=False))
        self.assertEqual(ledger.claims["c"].status, ClaimStatus.PROPOSED)

    def test_dependency_reopens_without_refuting_conclusion(self):
        ledger = ClaimLedger()
        ledger.add_claim(Claim("a", 1, "Premise", "gpt-oss"))
        ledger.add_claim(Claim("b", 1, "Conclusion", "command",
                               status=ClaimStatus.SUPPORTED, dependencies=["a"]))
        ledger.attach(Evidence("e", "a", 1, EvidenceKind.TEST, "fail",
                               "specific case", "h", independently_checked=True))
        self.assertEqual(ledger.claims["a"].status, ClaimStatus.CONTRADICTED)
        self.assertEqual(ledger.claims["b"].status, ClaimStatus.UNRESOLVED)
        self.assertTrue(ledger.claims["b"].needs_re_evaluation)

    def test_family_quorum_counts_families(self):
        self.assertEqual(quorum({"glm", "nemotron", "minimax"}), 2)
        self.assertEqual(FAMILIES["nemotron"].endpoints[0].provider, "OpenRouter")
        validate_assignment(("gpt-oss", "command", "nemotron"), "gemini", "glm")
        with self.assertRaises(ValueError):
            validate_assignment(("gpt-oss", "gemini"), "gemini", "glm")

    def test_json_parser_never_evaluates(self):
        self.assertEqual(parse_object('text ```json\\n{"x": 2}\\n```')["x"], 2)
        with self.assertRaises(OutputError):
            parse_object("not JSON")

    def test_cache_keys_include_model_and_sample(self):
        args = dict(provider="Groq", model="a", messages=[{"role":"user","content":"x"}],
                    settings={"temperature":0}, prompt_version="v1", sample_id="s1")
        first = response_cache_key(**args)
        self.assertNotEqual(first, response_cache_key(**{**args, "model":"b"}))
        self.assertNotEqual(first, response_cache_key(**{**args, "sample_id":"s2"}))

    def test_events_replay_from_sqlite(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d), "id") as store:
                store.record("run_started", question="q")
                store.record("run_finished", result={"ok":True})
                self.assertEqual([x["event"] for x in store.replay()],
                                 ["run_started", "run_finished"])
                self.assertTrue(store.logfile.is_file())

    def test_arithmetic_check_scoped(self):
        self.assertEqual(check("31*5-2", 153).outcome, "pass")
        self.assertEqual(check("31*5-2", 154).outcome, "fail")
        self.assertEqual(calculate("2**8 % 13"), 9)
        self.assertEqual(check("__import__('os')", 0).outcome, "error")
        self.assertEqual(check("2**20000", 1).outcome, "error")

if __name__ == "__main__":
    unittest.main()

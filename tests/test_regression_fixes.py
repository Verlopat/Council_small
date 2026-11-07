"""Offline regressions for RFC-aware judging and claim filtering.

No provider credentials, network calls, or paid APIs are used.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from council.claim_filter import close_to_owner, is_meta_claim
from council.judge import blind_ledger
from council.models import Claim, ClaimLedger
from council.plan_sanity import is_plan_instead_of_answer
from council.schemas import validate
from council.verify.source import PaperIndex
from council.vrf_audit import scan_audit_issues
from council.vrf_sanity import scan_vrf_games
from router_health import HealthCache


class RegressionFixTests(unittest.TestCase):
    def test_rfc_excerpt_stops_at_next_section_heading(self):
        document = "\n".join([
            "Request for Comments: 9381",
            "3.1. Full Uniqueness",
            "Full uniqueness text " * 24,
            "3.2. Full Collision Resistance",
            "A different security property.",
            "3.3. Trusted Uniqueness and Trusted Collision Resistance",
            "Trusted uniqueness text " * 24,
            "3.4. Full Pseudorandomness or Selective Pseudorandomness",
            "Full pseudorandomness challenge " * 35,
            "3.5. Trusted Pseudorandomness",
            "Do not include this next section.",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            index = PaperIndex(Path(tmp) / "references.sqlite3")
            try:
                index.add(
                    "rfc9381", "RFC 9381", document,
                    license="Test only",
                    source_uri="https://www.rfc-editor.org/rfc/rfc9381.txt")
                for number, next_heading in (
                    ("3.1", "3.2."), ("3.3", "3.4."), ("3.4", "3.5.")
                ):
                    result = index.rfc_section_excerpt(number)
                    self.assertIsNotNone(result)
                    self.assertNotIn(next_heading, result["excerpt"])
                    self.assertFalse(result["truncated"])
                    self.assertIn(number + ".", result["excerpt"])
                short = index.rfc_section_excerpt("3.4", max_chars=300)
                self.assertEqual(len(short["excerpt"]), 300)
                self.assertTrue(short["truncated"])
            finally:
                index.close()

    def test_rfc_excerpt_refuses_unapproved_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = PaperIndex(Path(tmp) / "other.sqlite3")
            try:
                index.add(
                    "rfc9381", "Pretend RFC",
                    "3.1. Full Uniqueness\nNot from the RFC.",
                    license="Test", source_uri="https://example.org/other")
                self.assertIsNone(index.rfc_section_excerpt("3.1"))
            finally:
                index.close()

    def test_duplicate_requires_similar_claim_not_shared_quote(self):
        owner = SimpleNamespace(
            id="p1:c1",
            statement="Full uniqueness prohibits two distinct VRF outputs for one input.",
            source_span="This sentence includes both ideas.")
        self.assertEqual(close_to_owner(owner.statement, [owner]), "p1:c1")
        rival = ("Trusted uniqueness requires honest key generation even when "
                 "the adversary knows the secret key.")
        self.assertIsNone(close_to_owner(rival, [owner]))

    def test_meta_claims_are_generic(self):
        for statement in ("The answer defines a security game.",
                          "This proposal describes a new algorithm.",
                          "The response outlines an approach.",
                          "The brief summarizes the topic."):
            self.assertTrue(is_meta_claim(statement))
        self.assertFalse(is_meta_claim(
            "Trusted uniqueness holds for an honestly generated key pair."))

    def test_request_invalid_does_not_poison_model_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = HealthCache(Path(tmp) / "health.json", clock=lambda: 100.0)
            cache.failure("Groq", "openai/gpt-oss-120b", "request_invalid")
            self.assertIsNone(cache.blocked("Groq", "openai/gpt-oss-120b"))
            cache.failure("Groq", "openai/gpt-oss-120b", "server")
            self.assertIsNotNone(cache.blocked("Groq", "openai/gpt-oss-120b"))

    def test_task_list_on_one_line_is_still_a_plan(self):
        question = "Explain the full, trusted, and pseudorandom VRF security games."
        approach = ("[S1] Define the full uniqueness game. "
                    "[S2] Specify the trusted uniqueness assumptions. "
                    "[S3] Describe the pseudorandomness challenger.")
        self.assertTrue(is_plan_instead_of_answer(question, approach))

    def test_hunter_accepts_structured_provider_text(self):
        result = validate("hunter", {
            "found": True,
            "counterexample": ["first observation", "second observation"],
            "tried": [{"step": 1}, ["nested", "text"], "manual check"],
            "check_artifact": {},
        })
        self.assertIsInstance(result["counterexample"], str)
        self.assertEqual(len(result["tried"]), 3)
        self.assertTrue(all(isinstance(x, str) for x in result["tried"]))

    def test_compact_ledger_retains_flagged_claim(self):
        ledger = ClaimLedger()
        for n in range(35):
            ledger.add_claim(Claim(
                id=f"p1:c{n}", version=1,
                statement=("Long candidate security statement " * 12) + str(n),
                owner_family="gpt-oss"))
        compact = blind_ledger(
            ledger, max_chars=2500,
            warning_kinds={"p1:c0": ["trusted_uniqueness_sk_secrecy_contradiction"]})
        doc = json.loads(compact)
        self.assertLessEqual(len(compact), 2500)
        self.assertIn("p1:c0", [row["id"] for row in doc["records"]])
        self.assertIn("p1:c0", doc["all_blocking_claim_ids"])

    def test_vrf_warnings_apply_to_auditor_too(self):
        question = "Explain VRF full uniqueness, trusted uniqueness and pseudorandomness."
        suspect = (
            "Trusted uniqueness aborts if the adversary learns the secret key SK.")
        findings = scan_vrf_games(question, [
            SimpleNamespace(id="p1:c2", statement=suspect)])
        self.assertIn("trusted_uniqueness_sk_secrecy_contradiction",
                      {row["kind"] for row in findings})
        audit = scan_audit_issues(question, [suspect])
        self.assertIn("trusted_uniqueness_sk_secrecy_contradiction",
                      {row["kind"] for row in audit})

    def test_uniqueness_requires_distinct_outputs(self):
        question = "Explain VRF full uniqueness and pseudorandomness."
        suspect = ("Full uniqueness is broken by two distinct proofs "
                   "for the same output under one public key and input.")
        findings = scan_vrf_games(question, [
            SimpleNamespace(id="p2:c1", statement=suspect)])
        self.assertIn("uniqueness_on_proofs",
                      {row["kind"] for row in findings})


if __name__ == "__main__":
    unittest.main()

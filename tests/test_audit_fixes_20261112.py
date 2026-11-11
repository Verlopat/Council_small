"""Regression tests for the November 2026 fail-closed Council audit."""
from __future__ import annotations
import asyncio
import contextlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock

from council.budget import RunBudget
from council.final_answers import extract_final_answer, normalize_answer
from council.parse import OutputError, parse_object
from council.quota import QuotaScheduler, QuotaContention
from council.replay import ResumeTransport
from council.schemas import validate
from council.verify.author_check import recompute_answer
from council.verify.python_exec import CheckSpecification, evaluate_spec
from council.verify.sandbox import SandboxResult
from council.verify.source import PaperIndex
from council.workflow import CouncilRunner
from answer_validation import matches_expected


class FailClosedJsonTests(unittest.TestCase):
    def test_truncated_nested_hunter_is_not_an_abstention(self):
        with self.assertRaises(OutputError):
            parse_object('{"found":true,"check_artifact":{"witness":"x"}')
        self.assertEqual(parse_object('Here is JSON: {"found":true}'), {"found": True})

    def test_partial_review_and_hunter_are_not_empty_valid_votes(self):
        for role, payload in [
            ("hunter", {"check_artifact": {}}),
            ("review", {"unrelated": "ignored previously"}),
            ("audit", {"suggested_checks": []}),
        ]:
            with self.subTest(role=role), self.assertRaises(ValueError):
                validate(role, payload)
        self.assertEqual(validate("review", {"objections": []}), {"objections": []})
        self.assertFalse(validate("hunter", {"found": False})["found"])

    def test_last_final_answer_not_first_operand(self):
        self.assertEqual(extract_final_answer("Final answer: 12 * 13 = 156"), "156")
        self.assertEqual(extract_final_answer("Final answer: 1/2"), "1/2")
        self.assertEqual(extract_final_answer("Final answer: no solution exists"),
                         "no solution")
        self.assertEqual(extract_final_answer(
            "Final answer: no. Correction: Final answer: yes"), "yes")
        self.assertIsNone(extract_final_answer("Final answer: 12 * 13 = "))

    def test_exact_fraction_and_no_solution_scoring(self):
        self.assertTrue(matches_expected("Final answer: 12 * 13 = 156", "156"))
        self.assertTrue(matches_expected("Final answer: 1/2", "0.5"))
        self.assertTrue(matches_expected("Final answer: no solution exists",
                                         "no solution"))
        self.assertFalse(matches_expected("Final answer: 12 * 13 = 157", "156"))


class ClaimPersistenceTests(unittest.TestCase):
    def test_invalid_duplicate_local_id_leaves_no_claim(self):
        runner = CouncilRunner(object(), object(), RunBudget.start(60),
                               solvers=("gpt-oss",), judge_family="gemini",
                               auditor_family="gemma")
        payload = {
            "approach": "A valid enough approach.",
            "claims": [
                {"id": "c1", "statement": "The first claim."},
                {"id": "c1", "statement": "A duplicate local identifier."},
            ],
        }
        with self.assertRaises(OutputError):
            runner._proposal("gpt-oss", payload, 1)
        self.assertEqual(runner.ledger.claims, {})

    def test_response_only_revision_is_permitted_by_schema(self):
        result = validate("revision", {
            "responses": [{"objection_id": "o1", "disposition": "reject",
                           "explanation": "Counterargument."}],
            "revised_claims": [],
        })
        self.assertIsNone(result.get("revised_approach"))
        self.assertEqual(len(result["responses"]), 1)


class VerificationTests(unittest.TestCase):
    def test_original_failing_property_check_reports_fail(self):
        spec = CheckSpecification(
            statement="A local property", code="print('no')",
            valid_examples=("print('yes')",),
            invalid_examples=("print('no')",),
            limitation="Only local fixtures", claim_version=1)
        with patch("council.verify.python_exec.run_python",
                   return_value=SandboxResult("fail", "sandbox completed")):
            result = evaluate_spec(spec)
        self.assertEqual(result.outcome, "fail")

    def test_decimal_roundoff_not_inconsistent(self):
        with patch("council.verify.author_check.run_python",
                   return_value=SandboxResult("ok", "sandbox completed",
                                               "0.30000000000000004\n")):
            self.assertEqual(recompute_answer("print(0.1+0.2)", "0.3")[0],
                             "pass")
        with patch("council.verify.author_check.run_python",
                   return_value=SandboxResult("ok", "sandbox completed", "4\n")):
            self.assertEqual(recompute_answer("print(4)", "3")[0], "fail")
        with patch("council.verify.author_check.run_python",
                   return_value=SandboxResult("ok", "sandbox completed",
                                               "10000000001.1\n")):
            self.assertEqual(recompute_answer("print(10000000001.1)",
                                              "10000000000.1")[0], "fail")

    def test_quoted_line_wrap_and_soft_hyphen(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = PaperIndex(Path(directory) / "source.sqlite3")
            corpus.add("rfc", "RFC", "A cryptographic veri-\nfication is sound.",
                       license="test")
            self.assertTrue(corpus.quote("rfc",
                                        "A cryptographic verification is sound.").found)
            self.assertFalse(corpus.quote("rfc", "does not exist").found)


class QuotaTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_rpm_bucket_shared_by_model_endpoints(self):
        quota = QuotaScheduler(default_rate=100, default_burst=5)
        quota.configure_provider("Gemini", rate_per_minute=10, burst=1)
        await quota.acquire("Gemini", "model-one",
                            deadline=time.monotonic() + 1)
        with self.assertRaises(QuotaContention):
            await quota.acquire("Gemini", "model-two",
                                deadline=time.monotonic() + 0.02)
        self.assertEqual(quota.shared_usage["Gemini"], 1)

    async def test_provider_daily_request_cap_shared_by_models(self):
        quota = QuotaScheduler(default_rate=100, default_burst=5)
        quota.configure_provider("Gemini", rate_per_minute=100,
                                 burst=3, daily_requests=1)
        await quota.acquire("Gemini", "model-one", deadline=time.monotonic()+1)
        with self.assertRaises(QuotaContention):
            await quota.acquire("Gemini", "model-two", deadline=time.monotonic()+1)


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_prior_unavailability_retries_live(self):
        events = [{"event": "role_unavailable",
                   "payload": {"family": "gemini", "role": "judge",
                               "failures": ["rate_limit"]}}]
        live = type("Live", (), {})()
        live.complete = AsyncMock(return_value="live-result")
        replay = ResumeTransport(events, live)
        answer = await replay.complete("gemini", "input", RunBudget.start(30),
                                       role="judge")
        self.assertEqual(answer, "live-result")
        live.complete.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

"""Regressions for formatted answers, brace-prefixed JSON and persisted quotas."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from council.final_answers import (
    canonical_scalar, executed_answer_selection, extract_final_answer,
    normalize_answer,
)
from council.models import Claim, ClaimLedger
from council.parse import OutputError, parse_object
from council.quota import QuotaContention, QuotaScheduler
from council.verify.author_check import _canonical, recompute_answer
from council.verify.sandbox import SandboxResult


class FormattedAnswerTests(unittest.TestCase):
    def test_common_model_phrasing_and_ambiguous_values(self):
        cases = {
            "Final answer: 13.": "13",
            "Final answer: 13 units": "13",
            "Final answer: $156": "156",
            "Final answer: Yes, they are equal.": "yes",
            "Final answer: 13": "13",
            "12 apples and 3 pears": None,
            "13 (mod 29)": None,
            "Final answer: 12 apples and 3 pears": None,
            "Final answer: 13 (mod 29)": None,
            "Final answer: no solution.": "no solution",
            "Final answer: 1/2": "1/2",
            "Final answer: 3.14.": "3.14",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_answer(raw), expected)
                if raw.startswith("Final answer: "):
                    self.assertEqual(extract_final_answer(raw), expected)

    def test_exact_canonical_fractions_and_no_solution(self):
        for input_value, expected in (
            ("1/2", "1/2"), ("0.5", "1/2"), ("1e3", "1000"),
            ("no solution", "no solution"), (False, "no"),
            ("1/0", None), ("13 (mod 29)", None)
        ):
            with self.subTest(input_value=input_value):
                self.assertEqual(canonical_scalar(input_value), expected)
                self.assertEqual(_canonical(input_value), expected)

    def test_author_code_supports_fraction_roundoff_and_no_solution(self):
        for output, claimed, expected in (
            ("0.5\n", "1/2", "pass"),
            ("'1/2'\n", "0.5", "pass"),
            ("'no solution'\n", "no solution", "pass"),
            ("'no solution'\n", "1/2", "fail"),
            ("0.3333333333333333\n", "1/3", "pass"),
            ("0.5\n", "1/3", "fail"),
        ):
            with self.subTest(output=output, claimed=claimed):
                capture = {}
                with patch("council.verify.author_check.run_python",
                           return_value=SandboxResult(
                               "ok", "sandbox completed", stdout=output)):
                    result, _ = recompute_answer(
                        "print('fake')", claimed, capture=capture)
                self.assertEqual(result, expected)
                self.assertIn("value", capture)

    def test_executed_fraction_agreement_is_unverified(self):
        ledger = ClaimLedger()
        proposals = []
        for i, (family, output) in enumerate(
                (("gpt-oss", "0.5"), ("command", "1/2"))):
            pid = f"p{i}"
            code = "print(" + repr(output) + ")"
            ledger.add_claim(Claim(
                pid + ":answer", 1, "Reported final scalar result: 7",
                family))
            proposals.append({
                "id": pid, "family": family, "final_answer": "7",
                "executed_answer": output,
                "artifact": {"code": code},
                "answer_claim_id": pid + ":answer",
                "claim_ids": [pid + ":answer"],
                "executed_claim_version": 1,
                "executed_artifact_hash": hashlib.sha256(
                    code.encode()).hexdigest(),
            })
        selected = executed_answer_selection(
            proposals, ledger.claims.values(), [])
        self.assertEqual(selected["answer"], "1/2")
        self.assertEqual(selected["basis"],
                         "executed_agreement_not_formal_proof")


class JsonWithMathTests(unittest.TestCase):
    def test_brace_before_fenced_json(self):
        fence = chr(96) * 3
        raw = ("Sure. Let S = {1,2}. Then:\n" + fence + "json\n"
               + '{"found": false, "tried": ["a"]}' + "\n" + fence)
        self.assertEqual(parse_object(raw),
                         {"found": False, "tried": ["a"]})

    def test_brace_before_line_start_json(self):
        raw = r"\boxed{5}" + '\n{"a": 1}'
        self.assertEqual(parse_object(raw), {"a": 1})

    def test_prefer_fenced_json_to_other_brace_content(self):
        fence = chr(96) * 3
        raw = '{"bad": 1}\n' + fence + 'json\n{"found":false}\n' + fence
        self.assertEqual(parse_object(raw), {"found": False})

    def test_truncated_outer_object_never_decodes_nested_object(self):
        for raw in (
            '{"found": true, "details": {\n  "found": false\n}',
            '{"found": true, "details": [\n  {"found": false}\n]',
        ):
            with self.subTest(raw=raw), self.assertRaises(OutputError):
                parse_object(raw)


class PersistedQuotaTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def quota(path, *, daily_requests=None, daily_tokens=None,
              tokens_per_minute=None):
        q = QuotaScheduler(
            default_rate=600, default_burst=10, daily_state_file=path)
        q.configure_provider(
            "Groq", rate_per_minute=600, burst=10,
            daily_requests=daily_requests, daily_tokens=daily_tokens,
            tokens_per_minute=tokens_per_minute)
        return q

    async def test_oversize_estimate_uses_one_full_tpm_bucket(self):
        q = self.quota(None, tokens_per_minute=100)
        await q.acquire("Groq", "a", deadline=time.monotonic()+1,
                        expected_tokens=900)
        self.assertGreaterEqual(q.shared_tpm_available["Groq"], -0.01)
        self.assertLess(q.shared_tpm_available["Groq"], 1)
        with self.assertRaises(QuotaContention):
            await q.acquire("Groq", "b", deadline=time.monotonic()+.02,
                            expected_tokens=1)

    async def test_daily_request_cap_survives_another_scheduler(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".council_daily_quotas.json"
            q1 = self.quota(path, daily_requests=1)
            await q1.acquire("Groq", "a", deadline=time.monotonic()+1)
            q2 = self.quota(path, daily_requests=1)
            with self.assertRaises(QuotaContention):
                await q2.acquire("Groq", "b", deadline=time.monotonic()+1)
            state = json.loads(path.read_text())
            self.assertEqual(state["providers"]["Groq"]["requests"], 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    async def test_actual_tokens_reconcile_across_scheduler_restarts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "daily.json"
            q1 = self.quota(path, daily_tokens=100)
            await q1.acquire("Groq", "a", deadline=time.monotonic()+1,
                             expected_tokens=80)
            q1.observe("Groq", "a", {}, input_tokens=20,
                       output_tokens=30, reserved_tokens=80)
            q2 = self.quota(path, daily_tokens=100)
            await q2.acquire("Groq", "b", deadline=time.monotonic()+1,
                             expected_tokens=50)
            q3 = self.quota(path, daily_tokens=100)
            with self.assertRaises(QuotaContention):
                await q3.acquire("Groq", "c", deadline=time.monotonic()+1,
                                 expected_tokens=1)
            self.assertEqual(json.loads(path.read_text())
                             ["providers"]["Groq"]["tokens"], 100)

    async def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "daily.json"
            path.write_text("{invalid-json")
            q = self.quota(path, daily_requests=5)
            with self.assertRaises(QuotaContention):
                await q.acquire("Groq", "a", deadline=time.monotonic()+1)
            self.assertEqual(path.read_text(), "{invalid-json")

    async def test_utc_day_rollover_resets_persisted_account(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "daily.json"
            yesterday = (datetime.now(timezone.utc)-timedelta(days=1)
                         ).date().isoformat()
            path.write_text(json.dumps({
                "version": 1, "providers": {
                    "Groq": {"day": yesterday, "requests": 10, "tokens": 500}}}))
            q = self.quota(path, daily_requests=1, daily_tokens=100)
            await q.acquire("Groq", "a", deadline=time.monotonic()+1,
                            expected_tokens=50)
            self.assertEqual(json.loads(path.read_text())
                             ["providers"]["Groq"]["requests"], 1)

    async def test_daily_cap_survives_separate_python_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "daily.json"
            script = (
                "import asyncio,sys,time\n"
                "from pathlib import Path\n"
                "from council.quota import QuotaScheduler,QuotaContention\n"
                "q=QuotaScheduler(default_rate=600,default_burst=5,"
                "daily_state_file=Path(sys.argv[1]))\n"
                "q.configure_provider('Groq',rate_per_minute=600,"
                "burst=5,daily_requests=1)\n"
                "try:\n"
                " asyncio.run(q.acquire('Groq','a',deadline=time.monotonic()+2))\n"
                " print('allowed')\n"
                "except QuotaContention:\n"
                " print('blocked')\n"
            )
            cwd = Path(__file__).resolve().parents[1]
            outcomes = []
            for _ in range(2):
                process = subprocess.run(
                    [sys.executable, "-c", script, str(path)],
                    cwd=cwd, capture_output=True, text=True, timeout=8)
                self.assertEqual(process.returncode, 0, process.stderr)
                outcomes.append(process.stdout.strip())
            self.assertEqual(outcomes, ["allowed", "blocked"])


if __name__ == "__main__":
    unittest.main()

"""Offline regressions for source preflight, synthesis reserve and audit fallback."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from council.budget import RunBudget
from council.cli import main
from council.events import EventStore
from council.full import FullCouncilRunner
from council.transport import CallResult, FamilyUnavailable
from council.config import load_config


class FreeAuditTransport:
    def __init__(self):
        self.calls = []

    async def complete(self, family, message, budget, *, role, synthesis=False):
        self.calls.append((family, role, budget.end))
        if role == "audit" and family == "gemma":
            raise FamilyUnavailable("gemma", ["Ollama Cloud/gemma4:31b: billing_required"])
        if role == "proposal":
            body = {
                "approach": "2+2=4", "final_answer": "4",
                "claims": [{"id": "c1", "statement": "2+2=4",
                            "source_span": "2+2=4"}],
                "hypotheses": [], "experiments": []}
        elif role == "translate":
            body = {"claim_kind": "arithmetic", "scope": "2+2=4",
                    "artifact": {"expression": "2+2", "expected": 4}}
        elif role == "extract":
            body = {"claims": []}
        elif role == "judge":
            body = {"status": "answer", "answer": "4", "blocking": [],
                    "partial_answer": "4", "basis": []}
        elif role == "audit":
            body = {"issues": [], "suggested_checks": []}
        elif role == "hunter":
            body = {"found": False, "tried": []}
        else:
            body = {}
        return CallResult(family, "offline", "offline-model",
                          json.dumps(body), 0.01, "offline-hash")


class FullModeFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_audit_402_uses_distinct_fallback_and_preserves_judge_reserve(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = FreeAuditTransport()
            with EventStore(Path(temp), "fallback") as events:
                runner = FullCouncilRunner(
                    transport, events, RunBudget.start(120, 24),
                    auditor_fallbacks=("minimax",),
                    enable_repairs=False, hunter_cap=0, enable_coverage=False)
                result = await runner.run("Check the equality", mode="full")
                roles = [(family, role) for family, role, _ in transport.calls]
                self.assertIn(("gemma", "audit"), roles)
                self.assertIn(("minimax", "audit"), roles)
                self.assertEqual(result["role_coverage"]["actual_audit_family"],
                                 "minimax")
                self.assertTrue(result["role_coverage"]["independent_audit_completed"])
                self.assertEqual(result["role_coverage"]["audit_family"], "gemma")
                judge_end = next(end for _, role, end in transport.calls
                                 if role == "judge")
                audit_end = next(end for _, role, end in transport.calls
                                 if role == "audit")
                self.assertGreater(audit_end, judge_end)
                self.assertIn("auditor_fallback_selected",
                              [event["event"] for event in events.replay()])

    async def test_fallback_must_not_reuse_a_solver_or_the_judge(self):
        with tempfile.TemporaryDirectory() as temp:
            with EventStore(Path(temp), "invalid") as events:
                for fallback in ("gpt-oss", "gemini", "glm", "gemma", "unknown"):
                    with self.subTest(fallback=fallback):
                        with self.assertRaises(ValueError):
                            FullCouncilRunner(
                                FreeAuditTransport(), events,
                                RunBudget.start(60, 15),
                                auditor_fallbacks=(fallback,))


class SourceAlignmentSafetyTests(unittest.TestCase):
    def test_incomplete_definition_cannot_be_marked_fully_selected(self):
        from council.judge import normalize_topic_judgment
        source = {"section": "3.3", "excerpt": "Honestly generated keys with known SK.",
                  "truncated": False}
        versions = [{"id": "p1:c2", "statement": "Only honest keys.",
                     "flags": []}]
        opinion = {"versions": [{"id": "p1:c2", "status": "incomplete",
                                "reference_quote": "Honestly generated keys",
                                "reason": "Missing adversary's secret-key knowledge"}],
                   "best_version_id": "p1:c2"}
        result = normalize_topic_judgment(
            "trusted_uniqueness", source, versions, opinion)
        self.assertIsNone(result["best_version_id"])
        self.assertFalse(result["verified"])


class FullModePreflightTests(unittest.TestCase):
    def test_explicit_vrf_game_names_are_definition_requests(self):
        from council.definition_sources import is_vrf_definition_question
        question=("Define full uniqueness, trusted uniqueness, and "
                  "pseudorandomness for VRFs according to RFC 9381.")
        self.assertTrue(is_vrf_definition_question(question))
        self.assertFalse(is_vrf_definition_question(
            "Prove security of a VRF construction under LWE."))

    def test_missing_official_rfc_fails_before_live_api_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = Path.cwd()
            try:
                os.chdir(temp)
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors):
                    with self.assertRaises(SystemExit) as exc:
                        main(["--mode", "full", "--config", "missing.yaml",
                              "Define full uniqueness, trusted uniqueness, and "
                              "pseudorandomness for VRFs according to RFC 9381."])
                self.assertEqual(exc.exception.code, 2)
                self.assertIn("python -m council.rfc_index", errors.getvalue())
            finally:
                os.chdir(previous)

    def test_default_yaml_declares_only_unassigned_fallback(self):
        cfg = load_config(Path(__file__).resolve().parents[1] / "council.yaml")
        self.assertEqual(cfg.optional.get("audit_fallbacks"), ["minimax"])
        self.assertNotIn("minimax", set(cfg.solvers) |
                         {cfg.translator, cfg.judge, cfg.auditor})


if __name__ == "__main__":
    unittest.main()

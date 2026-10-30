"""Optional proof assistant, YAML and evaluation-plan regressions."""
import tempfile
import unittest
from pathlib import Path
from council.config import load_config
from council.assignment import RoleConflict,Assignment
from council.verify.domain import check
from eval.phase_a import plan

class ConfigurationTests(unittest.TestCase):
    def test_default_yaml_roles_are_disjoint(self):
        root=Path(__file__).resolve().parents[1]
        cfg=load_config(root/"council.yaml")
        self.assertEqual(cfg.mode,"full")
        self.assertEqual(cfg.assignment.judge,"gemini")
        self.assertNotIn(cfg.assignment.judge,cfg.assignment.solvers)
    def test_four_solver_mode_needs_distinct_auditor(self):
        with self.assertRaises(RoleConflict):
            Assignment(("gpt-oss","command","nemotron","gemma"),"glm","gemini","gemma")
        good=Assignment(("gpt-oss","command","nemotron","gemma"),"glm","gemini","minimax")
        self.assertEqual(len(good.solvers),4)
    def test_phase_a_is_plan_only(self):
        root=Path(__file__).resolve().parents[1]
        rows=plan(root/"eval"/"tasks"/"dev_research.jsonl",runs=3,call_budget=5)
        self.assertEqual(len(rows),90)
        self.assertTrue(all(r.council_calls_budget==r.baseline_calls_budget for r in rows))
    def test_formal_proof_adapter_rejects_holes(self):
        output=check("lean","theorem foo : True := by sorry")
        self.assertEqual(output.outcome,"inconclusive")
        with self.assertRaises(ValueError):
            check("unknown","abc")

if __name__=="__main__":
    unittest.main()

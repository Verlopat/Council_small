"""Committed evaluation splits stay balanced, independent and reproducible.

These are validation definitions only; no live API calls are made.
"""
import json
from collections import Counter
from pathlib import Path
import unittest

from eval.generate_tasks import build
from eval.tasks import load

ROOT=Path(__file__).resolve().parents[1]/"eval"/"tasks"

class EvaluationFixturesTests(unittest.TestCase):
    def test_research_split_balance_and_no_leakage(self):
        dev=load(ROOT/"dev_research.jsonl",split="dev")
        heldout=load(ROOT/"heldout_research.jsonl",split="heldout")
        self.assertEqual((len(dev),len(heldout)),(30,30))
        expected={"M":5,"P":5,"L":5,"C":5,"V":5,"O":5}
        for rows in (dev,heldout):
            self.assertEqual(dict(Counter(t["category"] for t in rows)),expected)
            self.assertTrue(all(t["source_type"]=="synthetic_scenario" for t in rows))
            self.assertTrue(all(t.get("rubric") for t in rows))
        self.assertFalse({t["id"] for t in dev}&{t["id"] for t in heldout})
        self.assertFalse({t["prompt"] for t in dev}&{t["prompt"] for t in heldout})

    def test_phase_a_splits_have_90_stable_tasks_each(self):
        dev=load(ROOT/"phase_a_dev.jsonl",split="dev")
        held=load(ROOT/"phase_a_heldout.jsonl",split="heldout")
        self.assertEqual((len(dev),len(held)),(90,90))
        for split,rows in (("dev",dev),("heldout",held)):
            self.assertEqual(dict(Counter(r["kind"] for r in rows)),
                             {"numeric":30,"code":30,"symbolic":30})
            self.assertEqual(rows,build(per_kind=30,seed=20261029,split=split))
        self.assertFalse({r["id"] for r in dev}&{r["id"] for r in held})
        self.assertFalse({r["prompt"] for r in dev}&{r["prompt"] for r in held})

    def test_combined_splits_cannot_leak_ids_or_prompts(self):
        dev=load(ROOT/"dev_research.jsonl",split="dev")+load(
            ROOT/"phase_a_dev.jsonl",split="dev")
        held=load(ROOT/"heldout_research.jsonl",split="heldout")+load(
            ROOT/"phase_a_heldout.jsonl",split="heldout")
        self.assertFalse({r["id"] for r in dev}&{r["id"] for r in held})
        self.assertFalse({r["prompt"] for r in dev}&{r["prompt"] for r in held})

if __name__=="__main__":
    unittest.main()

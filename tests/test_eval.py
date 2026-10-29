"""Evaluation baselines must not be confused with proofs or task-independent samples."""
import tempfile
import unittest
from pathlib import Path
from eval.baselines import majority,best_of_n
from eval.metrics import bootstrap_ci,paired_deltas,earns_its_place
from eval.ratings import Ratings
from eval.parameter_sweep import choose
from eval.regression_probe import make,compare
from eval.tasks import load

class EvaluationTests(unittest.TestCase):
    def test_majority_and_best_of_n_differ(self):
        outputs=["wrong","wrong","correct"]
        self.assertEqual(majority(outputs).answer,"wrong")
        self.assertEqual(best_of_n(outputs,lambda x:(x=="correct",1.0)).answer,
                         "correct")
    def test_ci_task_pairing(self):
        records=[
            {"task_id":"t1","system":"council","correct":1},
            {"task_id":"t1","system":"council","correct":1},
            {"task_id":"t1","system":"best_of_n","correct":0},
            {"task_id":"t2","system":"council","correct":0},
            {"task_id":"t2","system":"best_of_n","correct":1}]
        self.assertEqual(paired_deltas(records),[1.0,-1.0])
        self.assertEqual(bootstrap_ci([1.,1.],n=500,seed=42),(1.,1.,1.))
    def test_elo_is_rung_specific(self):
        r=Ratings()
        r.update("gemini","glm","numeric",1.0)
        self.assertEqual(r.get("gemini","symbolic"),1500.)
        self.assertGreater(r.get("gemini","numeric"),1500.)
    def test_threshold_sweep(self):
        choice=choose({.7:{"false_verified_rate":.2,"resolved":50},
                       .8:{"false_verified_rate":0,"resolved":20}})
        self.assertEqual(choice[0],.8)
    def test_regression_requires_scored_drop(self):
        older=[make("glm","m","t","different response",1)]
        changed=[make("glm","m","t","new wording",1)]
        self.assertEqual(compare(older,changed),[])
        self.assertEqual(len(compare(older,[make("glm","m","t","wrong",0)])),1)
    def test_heldout_is_separate(self):
        base=Path(__file__).resolve().parents[1]/"eval"/"tasks"
        dev=load(base/"dev_research.jsonl",split="dev")
        hold=load(base/"heldout_research.jsonl",split="heldout")
        self.assertTrue(dev and hold)
        self.assertFalse({r["id"] for r in dev}&{r["id"] for r in hold})

if __name__=="__main__":
    unittest.main()

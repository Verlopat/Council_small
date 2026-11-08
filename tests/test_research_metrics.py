"""Human research rubric is separate from self-graded model answers."""
import unittest
from pathlib import Path
from eval.research_metrics import HumanAnnotation,report
from eval.tasks import load

class ResearchMetricsTests(unittest.TestCase):
    def test_blinded_two_rater_aggregation(self):
        x=[HumanAnnotation("q","council","r1","missed_flaws",.25),
           HumanAnnotation("q","council","r2","missed_flaws",.75)]
        r=report(x)
        self.assertEqual(r["per_task"][0]["mean_score"],.5)
        self.assertEqual(r["per_task"][0]["raters"],2)
    def test_duplicate_rating_is_rejected(self):
        a=HumanAnnotation("q","council","r1","false_claims",.1)
        with self.assertRaises(ValueError):
            report([a,a])
    def test_six_research_behavior_types(self):
        folder=Path(__file__).resolve().parents[1]/"eval"/"tasks"
        dev=load(folder/"dev_research.jsonl",split="dev")
        heldout=load(folder/"heldout_research.jsonl",split="heldout")
        self.assertGreaterEqual(len(dev),6)
        self.assertGreaterEqual(len(heldout),6)
        self.assertFalse(set(x["id"] for x in dev) &
                         set(x["id"] for x in heldout))

if __name__=="__main__":
    unittest.main()

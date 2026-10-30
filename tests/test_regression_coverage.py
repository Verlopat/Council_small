"""Weekly probes must cover endpoints fairly and disclose partial results."""
import unittest
from unittest.mock import patch
from council.families import Endpoint
from eval.regression_live import inspect, coverage
from eval.regression_probe import make

class FakeRouter:
    def __init__(self, timeout):
        self.calls=[]
    def expand(self, candidate, seen):
        return [candidate]
    def generate(self, candidate, question, *, max_output_tokens=None):
        self.calls.append((candidate.provider,question))
        return "42"

class RegressionCoverageTests(unittest.TestCase):
    def test_round_robin_short_cap_samples_multiple_endpoints(self):
        pair=[("one",Endpoint("Groq","one")),
              ("two",Endpoint("Z.ai","two"))]
        router=FakeRouter(30)
        with patch("eval.regression_live.candidates",return_value=iter(pair)), \
             patch("eval.regression_live.Router",return_value=router), \
             patch("eval.regression_live.FamilyTransport._eligible",return_value=True), \
             patch("eval.regression_live.matches_expected",return_value=True):
            rows=inspect(max_requests=3)
        self.assertEqual([p.family for p in rows],["one","two","one"])
        self.assertEqual(len(rows),3)
        self.assertFalse(coverage(rows)["all_sampled_complete"])

    def test_all_twenty_each_can_be_complete(self):
        rows=[make(family,model,"t"+str(i),"42",1.0)
              for family,model in (("one","one"),("two","two"))
              for i in range(20)]
        report=coverage(rows)
        self.assertTrue(report["all_sampled_complete"])
        self.assertEqual(report["sampled_endpoints"],2)

    def test_zero_records_are_not_complete(self):
        self.assertFalse(coverage([])["all_sampled_complete"])
    def test_reject_unbounded_opt_in(self):
        with self.assertRaises(ValueError):
            inspect(max_requests=1001)

if __name__=="__main__":
    unittest.main()

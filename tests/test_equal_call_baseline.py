"""Equal-call baseline planning must not mislabel capped samples as matched."""
import unittest
from unittest.mock import patch
from eval.execute import requested_baseline_calls, run_task
from council.transport import CallResult

class FakeEvents:
    def replay(self):
        return [{"event":"model_call_started"} for _ in range(8)]

class FakeCouncil:
    def __init__(self, *args, **kwargs):
        pass
    async def run(self, question):
        return {"research_result":{"proposed_approach":"42"},
                "verdict":{"status":"unresolved","answer":None},
                "composition":{"outcome":"unchecked"}}

class FakeTransport:
    async def complete(self, family, message, budget, *, role, synthesis=False):
        return CallResult(family, family, family+"-fake", "42", 0.01, "digest")

class BaselineBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_matches_calls_but_respects_hard_cap(self):
        self.assertEqual(requested_baseline_calls(23),23)
        self.assertEqual(requested_baseline_calls(23,user_limit=3),3)
        self.assertEqual(requested_baseline_calls(130),55)
        for value in (-1,):
            with self.assertRaises(ValueError):
                requested_baseline_calls(value)

    async def test_capped_baseline_is_flagged_unequal(self):
        task={"id":"t1","prompt":"What is 6*7?","expected":"42"}
        with patch("eval.execute.FullCouncilRunner",FakeCouncil):
            rows=await run_task(task,FakeTransport(),FakeEvents(),
                                deadline=20,baseline_samples=3)
        self.assertEqual(rows[0]["baseline_target_calls"],3)
        baseline=next(row for row in rows if row["system"]=="self_consistency")
        self.assertEqual(baseline["calls"],3)
        self.assertFalse(baseline["equal_budget"])

    async def test_default_matches_all_eight_call_samples(self):
        task={"id":"t2","prompt":"What is 6*7?","expected":"42"}
        with patch("eval.execute.FullCouncilRunner",FakeCouncil):
            rows=await run_task(task,FakeTransport(),FakeEvents(),
                                deadline=20,baseline_samples=0)
        base=next(row for row in rows if row["system"]=="self_consistency")
        self.assertEqual(base["calls"],8)
        self.assertTrue(base["equal_budget"])

if __name__=="__main__":
    unittest.main()

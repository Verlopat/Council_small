"""Generated tasks are reproducible, balanced, original and split-separated."""
import unittest
from eval.generate_tasks import build

class GeneratedTasksTests(unittest.TestCase):
    def test_three_rungs_thirty_each(self):
        rows=build(per_kind=30)
        self.assertEqual(len(rows),90)
        self.assertEqual({x["kind"] for x in rows},{"numeric","code","symbolic"})
        self.assertEqual(len({x["id"] for x in rows}),90)
        self.assertTrue(all(x["license"]=="original-generated" for x in rows))
        self.assertEqual(rows,build(per_kind=30))
    def test_heldout_is_independent(self):
        dev=build(per_kind=6,split="dev")
        test=build(per_kind=6,split="heldout")
        self.assertFalse({x["id"] for x in dev}&{x["id"] for x in test})
        self.assertNotEqual(dev[0]["prompt"],test[0]["prompt"])
    def test_gold_numeric_checks(self):
        from council.verify.arithmetic import calculate
        for row in build(per_kind=10):
            if row["kind"]=="numeric":
                self.assertEqual(int(calculate(row["checker_expression"])),
                                 int(row["expected"]))

if __name__=="__main__":
    unittest.main()

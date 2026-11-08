"""Formal-tool dispatch never certifies natural-language equivalence."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from council.translate import plan
from council.verify.ladder import verify

class FormalDispatchTests(unittest.TestCase):
    def test_missing_formal_artifact_is_unresolved(self):
        p=plan("c",1,"universal",scope="Every key verifies")
        outcome=verify(p,{})
        self.assertEqual(outcome.outcome,"unresolved")

    def test_formal_tool_called_and_scope_retained(self):
        p=plan("c",1,"universal",scope="For all x, P(x)")
        with patch("council.verify.ladder.domain_check",return_value=SimpleNamespace(
                outcome="pass",limitation="lean accepted formal input")) as tool:
            out=verify(p,{"tool":"lean","source":"theorem trivial : True := by trivial"})
        self.assertEqual(out.outcome,"pass")
        self.assertEqual(out.kind,"formal_proof")
        self.assertIn("not certified",out.limitation)
        tool.assert_called_once()

    def test_formal_tool_failure_is_not_pass(self):
        p=plan("c",1,"universal",scope="For all x, P(x)")
        with patch("council.verify.ladder.domain_check",return_value=SimpleNamespace(
                outcome="error",limitation="bwrap unavailable")):
            out=verify(p,{"tool":"lean","source":"theorem x : True := by trivial"})
        self.assertEqual(out.outcome,"error")

    def test_unknown_tool_not_executed(self):
        p=plan("c",1,"universal",scope="For all x, P(x)")
        with patch("council.verify.ladder.domain_check") as tool:
            out=verify(p,{"tool":"shell","source":"anything"})
        self.assertEqual(out.outcome,"unresolved")
        tool.assert_not_called()

if __name__=="__main__":
    unittest.main()

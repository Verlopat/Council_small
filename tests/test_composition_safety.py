"""Assembled numeric and prose outputs require their own evidence check."""
import unittest
from council.compose import compose_answer
from council.models import Claim, ClaimLedger, ClaimStatus

class AssembledAnswerTests(unittest.TestCase):
    def setUp(self):
        self.ledger=ClaimLedger()
        self.ledger.add_claim(Claim("c1",1,"2+2=4","gpt-oss",
                                    status=ClaimStatus.SUPPORTED))
    def test_correct_number_has_scoped_recomputation(self):
        result=compose_answer("4",["c1"],self.ledger)
        self.assertEqual(result.outcome,"pass")
        self.assertEqual(result.blocking,())
    def test_wrong_number_cannot_inherit_claim_support(self):
        result=compose_answer("5",["c1"],self.ledger)
        self.assertEqual(result.outcome,"unchecked")
        self.assertIn("assembled_number",result.blocking)
    def test_unmapped_prose_cannot_inherit_claim_support(self):
        result=compose_answer("The scheme is universally secure",["c1"],self.ledger)
        self.assertEqual(result.outcome,"unchecked")
        self.assertIn("unmapped_prose",result.blocking)
    def test_unsupported_numeric_claim_cannot_certify(self):
        self.ledger.claims["c1"].status=ClaimStatus.PROPOSED
        self.assertTrue(compose_answer("4",["c1"],self.ledger).blocking)
    def test_exact_prose_still_scoped(self):
        self.ledger.claims["c1"].statement="This candidate is a hypothesis."
        result=compose_answer("This candidate is a hypothesis.",["c1"],self.ledger)
        self.assertEqual(result.outcome,"scoped_support")

if __name__=="__main__":
    unittest.main()

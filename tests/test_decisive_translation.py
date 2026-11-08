"""Decisive-claim predicate never promotes model agreement into proof."""
import unittest
from council.models import Claim, ClaimLedger, ClaimStatus
from council.translate import decisive_if_supported

class DecisiveTests(unittest.TestCase):
    def test_single_claim_is_decisive(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("only",1,"conjecture","nemotron"))
        self.assertTrue(decisive_if_supported(ledger,"only"))
        self.assertEqual(ledger.claims["only"].status,ClaimStatus.PROPOSED)
    def test_other_unresolved_claim_blocks_decisiveness(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("a",1,"A","nemotron",status=ClaimStatus.SUPPORTED))
        ledger.add_claim(Claim("b",1,"B","command"))
        ledger.add_claim(Claim("c",1,"C","gpt-oss"))
        self.assertFalse(decisive_if_supported(ledger,"b"))
        ledger.claims["c"].status=ClaimStatus.SUPPORTED
        self.assertTrue(decisive_if_supported(ledger,"b"))
        self.assertFalse(decisive_if_supported(ledger,"a"))
    def test_unknown_claim_fails(self):
        with self.assertRaises(KeyError):
            decisive_if_supported(ClaimLedger(),"missing")

if __name__=="__main__":
    unittest.main()

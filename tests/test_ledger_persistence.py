"""Persistent ledger materialization preserves scopes, versions and dependency edges."""
import tempfile
from pathlib import Path
import unittest
from council.models import Claim,ClaimLedger,ClaimStatus,Evidence,EvidenceKind
from council.dependencies import Dependency
from council.ledger import SQLiteLedger

class LedgerPersistenceTests(unittest.TestCase):
    def test_snapshots_round_trip_without_status_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=ClaimLedger()
            ledger.add_claim(Claim("a",1,"Assumed claim","gpt-oss"))
            ledger.add_claim(Claim("b",1,"Dependent claim","command",
                                   status=ClaimStatus.UNRESOLVED))
            ledger.register_dependency(Dependency("a",1,"b",1,"Reduction step"))
            ledger.attach(Evidence("e1","a",1,EvidenceKind.SOURCE,"pass",
                           "a quote exists","abc",source_id="paper:1",
                           independently_checked=False))
            storage=SQLiteLedger(Path(root)/"ledger.sqlite3")
            storage.save("run-1",ledger)
            loaded=storage.load("run-1")
            self.assertEqual(loaded.claims["a"].status,ClaimStatus.PROPOSED)
            self.assertEqual(loaded.evidence["e1"].source_id,"paper:1")
            self.assertEqual(loaded.argument_dependencies.edges[0].argument,"Reduction step")
            loaded.revise("a","Different assumption")
            self.assertTrue(loaded.claims["b"].needs_re_evaluation)
            storage.close()

if __name__=="__main__":
    unittest.main()

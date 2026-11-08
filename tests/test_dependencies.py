"""Dependency arguments are versioned and losing a premise does not disprove a theorem."""
import unittest
from council.models import Claim,ClaimLedger,ClaimStatus,Evidence,EvidenceKind
from council.dependencies import Dependency

class DependencyTests(unittest.TestCase):
    def test_transitive_reopen(self):
        ledger=ClaimLedger()
        for identifier in ("A","B","C"):
            ledger.add_claim(Claim(identifier,1,"statement "+identifier,"family",
                                   status=ClaimStatus.SUPPORTED))
        ledger.register_dependency(Dependency("A",1,"B",1,"B follows by lemma A"))
        ledger.register_dependency(Dependency("B",1,"C",1,"C follows from B"))
        ledger.invalidate_dependents("A")
        self.assertEqual(ledger.claims["B"].status,ClaimStatus.UNRESOLVED)
        self.assertEqual(ledger.claims["C"].status,ClaimStatus.UNRESOLVED)
        self.assertTrue(all(not e.valid_support for e in ledger.argument_dependencies.edges))
        self.assertEqual(ledger.claims["A"].status,ClaimStatus.SUPPORTED)
    def test_cycles_and_stale_versions_rejected(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("A",1,"A","gpt-oss"))
        ledger.add_claim(Claim("B",1,"B","command"))
        ledger.register_dependency(Dependency("A",1,"B",1,"Because A"))
        with self.assertRaises(ValueError):
            ledger.register_dependency(Dependency("B",1,"A",1,"Because B"))
        with self.assertRaises(ValueError):
            ledger.register_dependency(Dependency("A",2,"B",1,"Stale"))
    def test_one_paper_is_one_confirmation(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("A",1,"Paper says X","gpt-oss"))
        for i in range(2):
            ledger.attach(Evidence("e"+str(i),"A",1,EvidenceKind.SOURCE,"pass",
                            "quote exists","different-hash-"+str(i),
                            source_id="doi:10.example/paper",
                            provenance=("family"+str(i),),independently_checked=False))
        self.assertEqual(ledger.distinct_evidence_sources("A"),
                         {"doi:10.example/paper"})
        self.assertEqual(ledger.claims["A"].status,ClaimStatus.PROPOSED)

if __name__=="__main__":
    unittest.main()

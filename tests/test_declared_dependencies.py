"""Model-declared arguments get provenance but no automatic proof authority."""
from pathlib import Path
import tempfile
import unittest
from council.budget import RunBudget
from council.events import EventStore
from council.full import FullCouncilRunner
from council.models import ClaimStatus

class DependencyExtractionTests(unittest.TestCase):
    def make(self, events):
        return FullCouncilRunner(None, events, RunBudget.start(30,5))

    def test_provisional_edges_register_and_are_versioned(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"deps") as events:
                runner=self.make(events)
                body={"approach":"Claims A and B","claims":[
                    {"id":"a","statement":"A"},
                    {"id":"b","statement":"B","depends_on":["a"],
                     "dependency_argument":"Assuming A, derive B"}]}
                proposal=runner._proposal("gpt-oss",body,1)
                runner._register_declared_dependencies(proposal,body)
                edges=runner.ledger.argument_dependencies.edges
                self.assertEqual(len(edges),1)
                self.assertFalse(edges[0].valid_support)
                self.assertEqual((edges[0].premise_id,edges[0].dependent_id),
                                 ("p1:c1","p1:c2"))
                self.assertEqual(runner.ledger.claims["p1:c2"].status,
                                 ClaimStatus.PROPOSED)
                self.assertTrue(any(e["event"]=="dependency_declared"
                                    for e in events.replay()))

    def test_missing_argument_and_unknown_premise_not_certified(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"bad") as events:
                runner=self.make(events)
                body={"approach":"Claims","claims":[
                    {"id":"a","statement":"A","depends_on":["missing"],
                     "dependency_argument":"Some argument"},
                    {"id":"b","statement":"B","depends_on":["a"]}]}
                proposal=runner._proposal("gpt-oss",body,1)
                runner._register_declared_dependencies(proposal,body)
                self.assertFalse(runner.ledger.argument_dependencies.edges)
                self.assertTrue(runner.warnings)
                self.assertTrue(runner.extra_obligations)

    def test_provisional_cycles_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with EventStore(Path(d),"cycle") as events:
                runner=self.make(events)
                body={"approach":"Cyclic claims","claims":[
                    {"id":"a","statement":"A","depends_on":["b"],
                     "dependency_argument":"A because B"},
                    {"id":"b","statement":"B","depends_on":["a"],
                     "dependency_argument":"B because A"}]}
                proposal=runner._proposal("gpt-oss",body,1)
                runner._register_declared_dependencies(proposal,body)
                self.assertEqual(len(runner.ledger.argument_dependencies.edges),1)
                self.assertTrue(any("Circular" in warning
                                    for warning in runner.warnings))

if __name__=="__main__":
    unittest.main()

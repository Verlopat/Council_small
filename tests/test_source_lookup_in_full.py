"""A real indexed quote is recorded as provenance, never a proved theorem."""
import json
import tempfile
import unittest
from pathlib import Path

from council.budget import RunBudget
from council.events import EventStore
from council.full import FullCouncilRunner
from council.transport import CallResult
from council.verify.source import PaperIndex
from council.models import EvidenceKind

class QuotationFake:
    async def complete(self,family,message,budget,*,role,synthesis=False):
        if role=="proposal":
            body={"answer":"The paper states conjecture X.",
                  "approach":"The paper states conjecture X.",
                  "claims":[{"id":"c1","statement":"The paper states conjecture X.",
                             "source_span":"The paper states conjecture X."}],
                  "hypotheses":[],"experiments":[]}
        elif role=="extract": body={"claims":[]}
        elif role=="review": body={"objections":[]}
        elif role=="translate":
            body={"claim_kind":"paper_description",
                  "scope":"Document contains the quoted assertion",
                  "artifact":{"document_id":"P1",
                              "quote":"The construction remains conjectural."}}
        elif role=="coverage": body={"missing_requirements":[]}
        elif role=="judge":
            body={"status":"unresolved","partial_answer":"Literature quotation located",
                  "blocking":[],"basis":[]}
        elif role=="audit": body={"issues":[],"suggested_checks":[]}
        else: body={}
        return CallResult(family,family+"-provider",family+"-mock",
                          json.dumps(body),0.001,"hash")

class SourceWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_local_corpus_is_consulted_without_certifying(self):
        with tempfile.TemporaryDirectory() as d:
            idx=PaperIndex(Path(d)/"papers.sqlite3")
            idx.add("P1","Research paper",
                    "The construction remains conjectural.",license="CC-BY-4.0")
            with EventStore(Path(d),"paper") as events:
                runner=FullCouncilRunner(
                    QuotationFake(),events,RunBudget.start(60,10),
                    paper_index=idx,hunter_cap=0,
                    enable_repairs=False,enable_coverage=False)
                result=await runner.run("What did the paper state?",mode="full")
                source=[e for e in result["evidence"]
                        if e["kind"]==EvidenceKind.SOURCE]
                self.assertTrue(source)
                self.assertFalse(any(e["independently_checked"] for e in source))
                self.assertEqual(result["research_result"]["checked_source_ids"],["P1"])
                self.assertEqual(result["research_result"]["supported_findings"],[])
                self.assertEqual(result["verdict"]["status"],"unresolved")
            idx.close()

if __name__=="__main__":
    unittest.main()

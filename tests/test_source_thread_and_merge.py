"""Cross-thread SQLite quote retrieval and conservative duplicate suggestions."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from council.verify.source import PaperIndex
from council.extract import suggest_duplicate_claims
from council.models import Claim

class PaperThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_and_quote_can_run_in_worker_thread(self):
        with tempfile.TemporaryDirectory() as folder:
            index=PaperIndex(Path(folder)/"papers.db")
            index.add("p","Paper","Lemma is a conjecture.",license="CC-BY")
            try:
                result=await asyncio.to_thread(index.quote,"p","a conjecture")
                self.assertTrue(result.found)
                found=await asyncio.to_thread(index.retrieve,"Lemma")
                self.assertEqual([x["id"] for x in found],["p"])
            finally:
                index.close()

class MergeSuggestionTests(unittest.TestCase):
    def test_identical_metadata_suggests_but_does_not_merge(self):
        left=Claim("a",1,"For every x, P(x).","gpt-oss",
                   quantifiers=["for every"],assumptions=["H"])
        right=Claim("b",1,"For every x, P(x).","command",
                    quantifiers=["for every"],assumptions=["H"])
        result=suggest_duplicate_claims([left,right])
        self.assertEqual(len(result),1)
        self.assertTrue(result[0]["metadata_equal"])
        self.assertEqual(result[0]["action"],"review_only")
    def test_assumption_change_never_merges(self):
        left=Claim("a",1,"The protocol may be secure.","gpt-oss",
                   assumptions=["LWE"])
        right=Claim("b",1,"The protocol may be secure.","command",
                    assumptions=["SIS"])
        result=suggest_duplicate_claims([left,right])
        self.assertEqual(len(result),1)
        self.assertFalse(result[0]["metadata_equal"])
    def test_threshold_is_validated(self):
        with self.assertRaises(ValueError):
            suggest_duplicate_claims([],threshold=1.1)

if __name__=="__main__":
    unittest.main()

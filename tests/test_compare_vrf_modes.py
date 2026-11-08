"""Offline test: five-run VRF mode comparison does not invent correctness."""
import csv
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from eval.compare_vrf_modes import (
    GAMES, ensure_scores, load_runs, recorded_provider_attempts)


class VRFModeComparisonTests(unittest.TestCase):
    def test_load_runs_and_annotation_template(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"quick_1.json").write_text(json.dumps({
                "research_result":{"completion_status":"partial"},
                "actual_models":[{"role":"proposal"},{"role":"judge"}],
                "proposals":[{"id":"p1"}],
                "topic_consolidation":[]}),encoding="utf-8")
            (folder/"full_1.json").write_text(json.dumps({
                "research_result":{"completion_status":"partial"},
                "actual_models":[{"role":"proposal"}]*7,
                "proposals":[{"id":"p1"},{"id":"p3"}],
                "topic_consolidation":[
                    {"topic":"full_uniqueness","best_version_id":"p3:c1"}]}),
                encoding="utf-8")
            runs=load_runs(folder,2)
            self.assertEqual(len(runs),4)
            self.assertEqual([x["found"] for x in runs],[True,False,True,False])
            self.assertEqual(runs[0]["calls"],2)
            self.assertEqual(runs[2]["calls"],7)
            self.assertEqual(runs[2]["selected"]["full_uniqueness"],"p3:c1")
            score_path=folder/"annotations.csv"
            self.assertEqual(ensure_scores(score_path,runs),{})
            with score_path.open(newline="",encoding="utf-8") as fh:
                records=list(csv.DictReader(fh))
            self.assertEqual(len(records),2*len(GAMES))
            self.assertTrue(all(x["correctness"]=="" for x in records))
            records[0]["correctness"]="1"
            with score_path.open("w",newline="",encoding="utf-8") as fh:
                writer=csv.DictWriter(fh,fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
            self.assertEqual(ensure_scores(score_path,runs),
                             {("quick",1,"full_uniqueness"):1.0})

    def test_api_attempt_counts_include_recorded_retries_and_failures(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp)
            run_id="abcdef0123456789"
            with sqlite3.connect(folder/(run_id+".sqlite3")) as conn:
                conn.execute("CREATE TABLE events (event_type TEXT)")
                conn.executemany("INSERT INTO events(event_type) VALUES (?)",[
                    ("model_call_started",),("model_call_retry",),
                    ("model_call_started",),("model_call_failed",)])
            (folder/"full_1.json").write_text(json.dumps({
                "run_id":run_id,
                "research_result":{"completion_status":"partial"},
                "actual_models":[{"role":"proposal"}],
                "proposals":[{"id":"p1"}]}))
            self.assertEqual(recorded_provider_attempts(folder,run_id),3)
            self.assertIsNone(recorded_provider_attempts(folder,"../etc/passwd"))
            self.assertIsNone(recorded_provider_attempts(folder,"missing_run"))
            rows=load_runs(folder,1)
            full=next(row for row in rows if row["mode"]=="full")
            self.assertEqual(full["calls"],1)
            self.assertEqual(full["attempts"],3)

    def test_invalid_annotation_grade_does_not_count(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp)
            fp=folder/"scores.csv"
            fp.write_text("mode,run,game,correctness,notes\n"
                          "full,1,pseudorandomness,1.5,invalid\n")
            with self.assertRaises(ValueError):
                ensure_scores(fp,[])


if __name__=="__main__":
    unittest.main()

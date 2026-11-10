"""Cross-module invariants for non-oracle paired quick/full verification.

All model interactions in this file are mocks; CI does not contact providers.
"""
import asyncio
import csv
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from council.transport import CallResult
from eval.compare_repeated_modes import summarize
from eval.compare_vrf_modes import ensure_scores,GAMES
from eval.execute import run_task
from eval.metrics import paired_deltas
from eval.run_eval import analyze


class Events:
    def replay(self):
        return [{"event":"model_call_started"} for _ in range(8)]


class FakeCouncil:
    options=[]
    def __init__(self,*args,**kwargs):
        self.options.append(kwargs)
    async def run(self,question,**kwargs):
        return {"research_result":{"completion_status":"partial",
                                   "proposed_approach":"Answer: 42"},
                "candidate_answers":{"p1":"42"},
                "final_answer":None,
                "proposals":[],
                "verdict":{"status":"unresolved"},
                "composition":{"outcome":"unchecked"}}


class ForbiddenBaselines:
    async def complete(self,*args,**kwargs):
        raise AssertionError("Baseline API must not be called")


class CrossModuleEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_baselines_avoids_all_extra_provider_calls(self):
        with patch("eval.execute.FullCouncilRunner",FakeCouncil):
            rows=await run_task(
                {"id":"numeric","kind":"numeric","prompt":"Answer 42",
                 "expected":"42"},
                ForbiddenBaselines(),Events(),deadline=20,
                run_baselines=False)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["correct"],1)
        self.assertEqual(rows[0]["baseline_target_calls"],0)
        self.assertEqual(rows[0]["calls"],8)

    async def test_evaluation_obeys_configured_role_families(self):
        config=SimpleNamespace(
            solvers=("command","nemotron"),max_claims=5,hunter_cap=1,
            translator="glm",judge="gemini",auditor="gemma",
            caps={"messages":3},solver_strategies={
                "command":"code","nemotron":"direct"},
            optional={"coverage_llm":False,"repair_round":False})
        FakeCouncil.options.clear()
        with patch("eval.execute.FullCouncilRunner",FakeCouncil):
            await run_task(
                {"id":"x","prompt":"Answer 42","expected":"42"},
                ForbiddenBaselines(),Events(),deadline=20,
                runner_config=config,run_baselines=False)
        opts=FakeCouncil.options[-1]
        self.assertEqual(opts["solvers"],("command","nemotron"))
        self.assertEqual(opts["translator_family"],"glm")
        self.assertFalse(opts["enable_repairs"])
        self.assertEqual(opts["caps"],{"messages":3})
        FakeCouncil.options.clear()
        with patch("eval.execute.QuickCouncilRunner",FakeCouncil):
            await run_task(
                {"id":"x","prompt":"Answer 42","expected":"42"},
                ForbiddenBaselines(),Events(),deadline=20,
                runner_config=config,run_baselines=False,mode="quick")
        self.assertEqual(FakeCouncil.options[-1]["solver"],"command")

    async def test_normalized_votes_on_numeric_final_answers(self):
        calls=[]
        class FakeTransport:
            async def complete(self,family,message,budget,*,role,synthesis=False):
                calls.append(role)
                answers={"baseline":"The answer is 42",
                         "baseline_vote6":"Final answer: 42"}
                return CallResult(family,family,family,answers[role],
                                  .01,"digest")
        with patch("eval.execute.FullCouncilRunner",FakeCouncil):
            rows=await run_task(
                {"id":"t1","prompt":"Answer 42","kind":"numeric",
                 "expected":"42"},
                FakeTransport(),Events(),deadline=20,
                baseline_samples=3)
        self.assertEqual(next(x for x in rows if x["system"]=="self_consistency")["correct"],1)
        self.assertEqual(next(x for x in rows if x["system"]=="vote6")["correct"],1)
        self.assertEqual(calls.count("baseline"),3)


class OracleAndRepeatedScoreTests(unittest.TestCase):
    def test_oracle_assisted_baseline_excluded_from_fair_comparison(self):
        rows=[{"task_id":"a","system":"council","correct":0},
              {"task_id":"a","system":"best_of_n","correct":1,
               "oracle_assisted":True},
              {"task_id":"b","system":"council","correct":1},
              {"task_id":"b","system":"best_of_n","correct":None}]
        self.assertEqual(paired_deltas(rows),[])
        good=[{"task_id":"a","system":"council","correct":0},
              {"task_id":"a","system":"self_consistency","correct":1}]
        self.assertEqual(paired_deltas(good,baseline="self_consistency"),[-1.])

    def test_score_file_expansion_preserves_manual_grades(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            existing=[{"mode":"quick","run":1,"found":True},
                      {"mode":"full","run":1,"found":True}]
            fp=folder/"scores.csv"
            ensure_scores(fp,existing)
            with fp.open(newline="",encoding="utf-8") as src:
                rows=list(csv.DictReader(src))
            self.assertEqual(rows[0]["mode"],"quick")
            rows[0]["correctness"]="1"
            rows[0]["notes"]="Checked myself"
            with fp.open("w",newline="",encoding="utf-8") as out:
                w=csv.DictWriter(out,fieldnames=rows[0].keys())
                w.writeheader();w.writerows(rows)
            expanded=existing+[
                {"mode":"quick","run":2,"found":True},
                {"mode":"full","run":2,"found":True}]
            self.assertEqual(ensure_scores(fp,expanded),
                             {("quick",1,GAMES[0]):1.})
            with fp.open(newline="",encoding="utf-8") as src:
                now=list(csv.DictReader(src))
            self.assertEqual(len(now),12)
            self.assertEqual(now[0]["notes"],"Checked myself")

    def test_repeated_comparison_resamples_distinct_tasks_not_repeats(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            grades={
                ("quick",1):{"a":0,"b":1},
                ("full",1):{"a":1,"b":1},
                ("quick",2):{"a":0,"b":0},
                ("full",2):{"a":1,"b":1},
            }
            for (mode,rep),scores in grades.items():
                path=root/f"{mode}_{rep}"
                path.mkdir()
                with (path/"results.jsonl").open("w") as out:
                    for tid,value in scores.items():
                        out.write(json.dumps({
                            "task_id":tid,"kind":"numeric",
                            "mode":mode,"system":"council",
                            "correct":value,"calls":2,
                            "latency":.02})+"\n")
            report=summarize(root,count=2)
            overall=report["paired"]["overall"]
            self.assertEqual(overall["distinct_scored_tasks"],2)
            self.assertEqual(overall["scored_replicate_pairs"],4)
            self.assertAlmostEqual(overall["full_minus_quick_mean"],.75)
            self.assertEqual(report["quick"]["total_reported_call_starts"],8)

    def test_repeated_comparison_refuses_mismatched_questions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for mode,tid in (("quick","a"),("full","b")):
                path=root/f"{mode}_1";path.mkdir()
                (path/"results.jsonl").write_text(json.dumps({
                    "task_id":tid,"kind":"numeric","mode":mode,
                    "system":"council","correct":1})+"\n")
            with self.assertRaises(ValueError):
                summarize(root,count=1)


class ScriptContractTests(unittest.TestCase):
    def test_benchmark_scripts_have_valid_shell_and_fresh_run_dir(self):
        if not shutil.which("bash"):
            self.skipTest("Requires bash")
        root=Path(__file__).resolve().parents[1]
        for name in ("benchmark_vrf_modes.sh","benchmark_phase_a_modes.sh"):
            script=root/"scripts"/name
            check=subprocess.run(["bash","-n",str(script)],
                                 capture_output=True,text=True,check=False)
            self.assertEqual(check.returncode,0,check.stderr)
            code=script.read_text()
            self.assertIn('RUN_DIR=',code)
            self.assertIn("council.preflight",code)
            self.assertIn('COUNT=',code)
            self.assertNotIn('rm -rf ',code)


if __name__=="__main__":
    unittest.main()

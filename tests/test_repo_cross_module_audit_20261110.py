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


class RoleAndCliPolicyTests(unittest.TestCase):
    def test_actual_role_assignment_not_legacy_global_role(self):
        from council.families import validate_assignment
        from council.budget import RunBudget
        from council.events import EventStore
        from council.full import FullCouncilRunner
        validate_assignment(("gpt-oss","glm"),"gemini",None)
        with tempfile.TemporaryDirectory() as td:
            with EventStore(Path(td),"assignment") as events:
                runner=FullCouncilRunner(
                    None,events,RunBudget.start(40),
                    solvers=("gpt-oss","glm"),
                    translator_family="gemma",
                    judge_family="gemini",
                    auditor_family=None)
                self.assertEqual(runner.assignment.solvers,("gpt-oss","glm"))
                self.assertIsNone(runner.auditor_family)
        with self.assertRaises(ValueError):
            validate_assignment(("gpt-oss","gemini"),"gemini",None)

    def test_cli_defaults_to_yaml_deadline_but_explicit_deadline_wins(self):
        import contextlib
        from io import StringIO
        from council.cli import main
        for overrides,expected in (([],600.0),(["--deadline","125"],125.0)):
            with self.subTest(overrides=overrides):
                output=StringIO()
                with contextlib.redirect_stdout(output):
                    result=main(["--mode","full","--dry-run",
                                 *overrides,"Explain a security game"])
                self.assertEqual(result,0)
                self.assertEqual(json.loads(output.getvalue())["deadline"],
                                 expected)

    def test_cli_explicit_timeout_is_strict_and_default_is_configured(self):
        import contextlib
        from io import StringIO
        from council.cli import main
        observed=[]
        class DummyTransport:
            def __init__(self,**kwargs):
                observed.append(kwargs)
        class DummyQuick:
            def __init__(self,*args,**kwargs):
                pass
            async def run(self,*args,**kwargs):
                return {"research_result":{"completion_status":"partial"},
                        "proposals":[]}
        with tempfile.TemporaryDirectory() as temp:
            for overrides,expected_strict,expected_timeout in (
                    ([],False,28.0),(["--timeout","60"],True,60.0)):
                with self.subTest(overrides=overrides):
                    output=StringIO()
                    with patch("council.cli.FamilyTransport",DummyTransport), \
                         patch("council.full.QuickCouncilRunner",DummyQuick), \
                         contextlib.redirect_stdout(output):
                        result=main([
                            "--mode","quick","--json","--run-dir",temp,
                            "--run-id","a"+str(len(observed)),
                            "--deadline","90",*overrides,
                            "Explain a security game"])
                    self.assertEqual(result,0)
                    self.assertEqual(observed[-1]["strict_timeout"],
                                     expected_strict)
                    self.assertEqual(observed[-1]["timeout"],expected_timeout)


class MissingAndRepeatMetricsTests(unittest.TestCase):
    def test_missing_code_accuracy_metrics_are_not_fabricated_or_crashing(self):
        from eval.metrics import summary
        result=summary([
            {"calls":3,"false_verified":None,
             "unresolved":True,"latency":.5},
            {"calls":5,"false_verified":None,
             "unresolved":False,"latency":1.5}])
        self.assertIsNone(result["false_verified"])
        self.assertIsNone(result["no_op"])
        self.assertEqual(result["calls"],4)
        self.assertEqual(result["latency"],1.)
        self.assertEqual(result["unresolved"],.5)

    def test_ordinary_quick_full_pairing_preserves_repeated_rows(self):
        from eval.run_eval import paired_mode_comparison
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for mode,corrects in (("quick",[0,1]),("full",[1,1])):
                dest=folder/mode
                dest.mkdir()
                with (dest/"results.jsonl").open("w") as fh:
                    for score in corrects:
                        fh.write(json.dumps({
                            "task_id":"repeat_me","kind":"numeric",
                            "system":"council","mode":mode,"correct":score})+"\n")
            result=paired_mode_comparison(folder/"quick",folder/"full")
            overall=result["overall"]
            self.assertEqual(overall["paired_tasks"],1)
            self.assertEqual(overall["paired_replicate_attempts"],2)
            self.assertEqual(overall["quick_accuracy"],.5)
            self.assertEqual(overall["full_accuracy"],1.)
            self.assertEqual(overall["full_minus_quick_ci"],(.5,.5,.5))


class CheckpointAndVoteTests(unittest.TestCase):
    def test_canonical_votes_do_not_split_equivalent_numeric_answers(self):
        from eval.execute import canonical_vote_answer
        self.assertEqual(canonical_vote_answer("Final answer: 42.0"),"42")
        self.assertEqual(canonical_vote_answer("Answer: 42"),"42")
        self.assertEqual(canonical_vote_answer("Answer: true"),"yes")
        self.assertEqual(canonical_vote_answer("Final answer: no"),"no")
        self.assertNotEqual(canonical_vote_answer("Answer: no"),"yes")

    def test_checkpoint_protects_existing_results_before_api_calls(self):
        from eval.execute import execute
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            prior=folder/"results.jsonl"
            prior.write_text('{"old":"valuable"}\n')
            async def attempt():
                await execute([{"id":"t1","prompt":"Answer 42"}],
                              out_dir=folder,deadline=10,
                              max_tasks=1,baseline_samples=0,
                              run_baselines=False)
            with patch("eval.execute.FamilyTransport") as transport:
                with self.assertRaises(FileExistsError):
                    asyncio.run(attempt())
                transport.assert_not_called()
            self.assertEqual(prior.read_text(),'{"old":"valuable"}\n')

    def test_interrupted_partial_results_cannot_be_overwritten(self):
        from eval.execute import execute
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            partial=folder/"results.partial.jsonl"
            partial.write_text('{"partial":"valuable"}\n')
            async def attempt():
                await execute([{"id":"t1","prompt":"Answer 42"}],
                              out_dir=folder,deadline=10,
                              max_tasks=1,baseline_samples=0,
                              run_baselines=False)
            with self.assertRaises(FileExistsError):
                asyncio.run(attempt())
            self.assertIn("valuable",partial.read_text())


class BenchmarkManifestTests(unittest.TestCase):
    def test_manifest_reuse_requires_exact_code_input_and_options(self):
        from eval.run_manifest import verify_manifest
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"runs"
            task=Path(temp)/"tasks.jsonl"
            task.write_text("original tasks")
            rev="a"*40
            before=verify_manifest(root,experiment="phase_a",
                                   inputs=[task],options="dev:3",
                                   revision=rev)
            again=verify_manifest(root,experiment="phase_a",
                                  inputs=[task],options="dev:3",
                                  revision=rev)
            self.assertEqual(before,again)
            with self.assertRaises(ValueError):
                verify_manifest(root,experiment="phase_a",
                                inputs=[task],options="dev:10",
                                revision=rev)
            with self.assertRaises(ValueError):
                verify_manifest(root,experiment="phase_a",
                                inputs=[task],options="dev:3",
                                revision="b"*40)
            task.write_text("different tasks")
            with self.assertRaises(ValueError):
                verify_manifest(root,experiment="phase_a",
                                inputs=[task],options="dev:3",
                                revision=rev)

    def test_unmanifested_prior_data_never_silently_reused(self):
        from eval.run_manifest import verify_manifest
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"runs";root.mkdir()
            task=Path(temp)/"tasks.jsonl";task.write_text("task")
            (root/"quick_1.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify_manifest(root,experiment="vrf",
                                inputs=[task],revision="a"*40)


class TranslatorRolePolicyTests(unittest.TestCase):
    def test_allocator_and_runner_agree_on_independent_fallbacks(self):
        from council.assignment import Assignment
        from council.full import FullCouncilRunner
        from council.budget import RunBudget
        from council.events import EventStore
        from council.models import Claim
        assignment=Assignment(
            ("gpt-oss","command","nemotron"),"glm","gemini","gemma")
        allowed=assignment.translator_candidates("gpt-oss")
        self.assertEqual(allowed,("glm","command","nemotron"))
        self.assertNotIn("gemma",allowed)
        self.assertNotIn("gemini",allowed)
        self.assertNotIn("gpt-oss",allowed)
        self.assertTrue(assignment.allowed(
            "translator","command",claim_owner="gpt-oss"))
        self.assertFalse(assignment.allowed(
            "translator","gemma",claim_owner="gpt-oss"))
        with tempfile.TemporaryDirectory() as folder:
            with EventStore(Path(folder),"policy") as events:
                runner=FullCouncilRunner(
                    None,events,RunBudget.start(60),
                    solvers=assignment.solvers,
                    translator_family=assignment.translator,
                    judge_family=assignment.judge,
                    auditor_family=assignment.auditor)
                self.assertEqual(
                    runner._translator_candidates(
                        Claim("p1:c1",1,"Test", "gpt-oss")),
                    list(allowed))

    def test_no_judge_or_auditor_role_reuse_via_fallback(self):
        from council.assignment import Assignment
        assignment=Assignment(
            ("gpt-oss","command"),"glm","gemini","nemotron")
        self.assertNotIn("nemotron",assignment.translator_candidates("gpt-oss"))
        self.assertNotIn("gemini",assignment.translator_candidates("gpt-oss"))


if __name__=="__main__":
    unittest.main()

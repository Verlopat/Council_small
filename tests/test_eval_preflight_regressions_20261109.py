"""Regress blank-answer scoring and Arch/venv bubblewrap home isolation.

Offline tests inspect the exact bwrap command. The target host must still
run council.preflight to establish that its kernel permits isolation.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from answer_validation import matches_expected
from council.preflight import Check, sandbox_report
from council.verify import sandbox
from eval.execute import main as eval_main


class MissingAnswerRegression(unittest.TestCase):
    def test_symbolic_answer_absent_or_blank_returns_false(self):
        for response in ("", "  ", "\n\t\n", None):
            for expected in ("yes", "no", "true", "false", "156"):
                with self.subTest(response=response, expected=expected):
                    self.assertFalse(matches_expected(response, expected))

    def test_empty_expected_never_matches_even_empty_response(self):
        for response in ("", " ", "anything"):
            self.assertFalse(matches_expected(response, ""))
            self.assertFalse(matches_expected(response, " \n "))

    def test_symbolic_terminal_answer_still_scores_correctly(self):
        self.assertTrue(matches_expected(
            "Algebraic calculation.\nFinal answer: yes", "yes"))
        self.assertTrue(matches_expected(
            "Counterexample at x=1.\nFinal answer: no", "false"))
        self.assertFalse(matches_expected(
            "Counterexample at x=1.\nFinal answer: no", "yes"))
        self.assertTrue(matches_expected("Answer: 156", "156"))


class SandboxHomeIsolationRegression(unittest.TestCase):
    def test_home_virtualenv_is_mounted_only_under_neutral_opt_path(self):
        # Original bug: --ro-bind /home/user/.../.venv /home/user/.../.venv
        # creates visible /home/user and fails host_home_isolation.
        host_prefix="/home/example/projects/council/.venv"
        python_exe=host_prefix+"/bin/python"
        completed=SimpleNamespace(
            stdout='{"pass": true}\n', stderr="", returncode=0)
        with patch.object(sandbox.sys, "prefix", host_prefix), \
             patch.object(sandbox.sys, "executable", python_exe), \
             patch.object(sandbox, "available", return_value=True), \
             patch.object(sandbox.subprocess, "run",
                          return_value=completed) as mocked:
            result=sandbox.run_python('print("{\\"pass\\":true}")')
        self.assertEqual(result.outcome, "pass")
        cmd=mocked.call_args.args[0]
        pairs=[(cmd[i+1],cmd[i+2]) for i,flag in enumerate(cmd[:-2])
               if flag in {"--bind","--ro-bind"}]
        self.assertIn((host_prefix,"/opt/council-python"),pairs)
        self.assertIn(("--dir","/opt"),list(zip(cmd,cmd[1:])))
        self.assertFalse(any(target.startswith("/home/")
                             for _source,target in pairs))
        self.assertEqual(
            cmd[cmd.index("--")+1],"/opt/council-python/bin/python")

    def test_interpreter_outside_virtualenv_is_rejected_without_execution(self):
        with patch.object(sandbox.sys,"prefix","/home/example/.venv"), \
             patch.object(sandbox.sys,"executable","/usr/bin/python3.14"), \
             patch.object(sandbox,"available",return_value=True), \
             patch.object(sandbox.subprocess,"run") as mocked:
            result=sandbox.run_python("print(1)")
        self.assertEqual(result.outcome,"error")
        self.assertEqual(result.detail,"interpreter_outside_prefix")
        mocked.assert_not_called()

    def test_preflight_explains_boolean_home_probe_failure(self):
        def check(source, *, timeout):
            if "host-home mountpoints" in source:
                return sandbox.SandboxResult("fail","sandbox completed")
            return sandbox.SandboxResult("pass","sandbox completed")
        with patch("council.preflight.available",return_value=True), \
             patch("council.preflight.run_python",side_effect=check):
            report=sandbox_report()
        self.assertEqual(report["host_home_isolation"].status,"fail")
        self.assertIn("pass=false",
                      report["host_home_isolation"].reason)
        self.assertEqual(report["network_isolation"].status,"pass")


class EvaluationFailClosedRegression(unittest.TestCase):
    def test_live_eval_requires_home_isolation_before_api_calls(self):
        unsafe={
            "execution":Check("pass","sandbox completed"),
            "network_isolation":Check("pass","sandbox completed"),
            "host_home_isolation":Check("fail","home visible"),
            "environment_isolation":Check("pass","sandbox completed"),
        }
        error=StringIO()
        with patch("eval.execute.load",return_value=[
            {"id":"t1","prompt":"2+2","expected":"4","split":"dev"}]), \
             patch("council.preflight.sandbox_report",return_value=unsafe), \
             patch("eval.execute.execute") as run, \
             redirect_stderr(error):
            with self.assertRaises(SystemExit) as raised:
                eval_main(["--tasks","unused.jsonl","--confirm-free",
                           "--max-tasks","1"])
        self.assertEqual(raised.exception.code,2)
        run.assert_not_called()
        self.assertIn("host_home_isolation",error.getvalue())

    def test_plan_only_does_not_require_or_execute_sandbox(self):
        output=StringIO()
        with patch("eval.execute.load",return_value=[
            {"id":"t1","prompt":"2+2","expected":"4","split":"dev"}]), \
             patch("council.preflight.sandbox_report") as preflight, \
             patch("eval.execute.execute") as run, \
             redirect_stdout(output):
            eval_main(["--tasks","unused.jsonl","--max-tasks","1"])
        self.assertIn("plan_only",output.getvalue())
        preflight.assert_not_called()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

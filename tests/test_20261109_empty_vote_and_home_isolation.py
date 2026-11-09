"""Regress real-world 2026-11-09 preflight and empty-vote failures.

The bwrap command is inspected using a mock; these tests do not claim
that the host kernel's namespace isolation was independently audited.
"""
from __future__ import annotations
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from answer_validation import matches_expected
from council.verify import sandbox


class EmptyVoteRegressionTests(unittest.TestCase):
    def test_missing_vote6_answers_are_incorrect_not_an_exception(self):
        for response in ("", " ", "\n\t", None):
            for expected in ("yes", "no", "true", "false", "42"):
                with self.subTest(response=response, expected=expected):
                    self.assertFalse(matches_expected(response, expected))
        self.assertFalse(matches_expected("", ""))
        self.assertFalse(matches_expected("no", ""))
        self.assertTrue(matches_expected("Final answer: no", "no"))


class HomeMountRegressionTests(unittest.TestCase):
    def test_virtualenv_is_read_only_at_neutral_path_not_host_home(self):
        process=SimpleNamespace(returncode=0,stdout='{"pass":true}\n',
                                stderr="")
        with patch.object(sandbox,"available",return_value=True), \
             patch.object(sandbox.sys,"prefix","/home/example/project/.venv"), \
             patch.object(sandbox.sys,"executable",
                          "/home/example/project/.venv/bin/python"), \
             patch.object(sandbox.subprocess,"run",return_value=process) as run:
            result=sandbox.run_python('print("{\\"pass\\":true}")')
        self.assertEqual(result.outcome,"pass")
        cmd=run.call_args.args[0]
        mounts=[(cmd[i+1],cmd[i+2]) for i,arg in enumerate(cmd)
                if arg=="--ro-bind"]
        self.assertIn(("/home/example/project/.venv",
                       "/opt/council-python"),mounts)
        self.assertFalse(any(dst=="/home" or dst.startswith("/home/")
                             for _src,dst in mounts))
        self.assertIn("/opt/council-python/bin/python",cmd)
        self.assertNotIn("/home/example/project/.venv/bin/python",cmd)
        self.assertIn("--unshare-all",cmd)
        self.assertIn("--clearenv",cmd)
        self.assertIn("--die-with-parent",cmd)

    def test_unrecognized_interpreter_layout_fails_without_execution(self):
        with patch.object(sandbox,"available",return_value=True), \
             patch.object(sandbox.sys,"prefix","/home/example/project/.venv"), \
             patch.object(sandbox.sys,"executable",
                          "/home/example/other/bin/python"), \
             patch.object(sandbox.subprocess,"run") as run:
            result=sandbox.run_python('print("{\\"pass\\":true}")')
        self.assertEqual(result.outcome,"error")
        run.assert_not_called()


if __name__=="__main__":
    unittest.main()

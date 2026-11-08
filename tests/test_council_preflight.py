"""Offline preflight checks never invoke a provider or unsafe host execution."""
import unittest
from unittest.mock import patch
from council import preflight
from council.verify.sandbox import SandboxResult

class PreflightTests(unittest.TestCase):
    def test_fails_closed_when_bwrap_missing(self):
        with patch.object(preflight, "available", return_value=False), \
             patch.object(preflight, "run_python") as runner:
            data=preflight.sandbox_report()
        self.assertEqual(data["sandbox"].status,"fail")
        runner.assert_not_called()

    def test_success_requires_each_isolation_check_to_pass(self):
        with patch.object(preflight,"available",return_value=True), \
             patch.object(preflight,"run_python",return_value=SandboxResult("pass","ok")) as runner:
            data=preflight.sandbox_report()
        self.assertEqual(len(data),4)
        self.assertTrue(all(x.status=="pass" for x in data.values()))
        self.assertEqual(runner.call_count,4)

    def test_any_failed_control_is_reported(self):
        outputs=[SandboxResult("pass","ok"), SandboxResult("error","blocked"),
                 SandboxResult("pass","ok"), SandboxResult("pass","ok")]
        with patch.object(preflight,"available",return_value=True), \
             patch.object(preflight,"run_python",side_effect=outputs):
            data=preflight.sandbox_report()
        self.assertEqual(data["network_isolation"].status,"fail")

if __name__=="__main__":
    unittest.main()

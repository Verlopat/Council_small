"""Locally denied calls must never poison provider health."""
import unittest
from council.quota import QuotaScheduler

class QuotaFailureClassification(unittest.TestCase):
    def test_local_contention_is_not_provider_failure(self):
        scheduler=QuotaScheduler()
        for _ in range(8):
            scheduler.failure("Groq","example",kind="quota_contention")
        state=scheduler.state("Groq","example")
        self.assertEqual(state.consecutive_failures,0)
        self.assertEqual(state.cooldown_until,0)

    def test_prompt_specific_error_is_not_provider_failure(self):
        scheduler=QuotaScheduler()
        scheduler.failure("Groq","example",kind="context_length")
        scheduler.failure("Groq","example",kind="request_invalid")
        self.assertEqual(scheduler.state("Groq","example").consecutive_failures,0)

    def test_server_errors_remain_counted(self):
        scheduler=QuotaScheduler()
        for _ in range(3):
            scheduler.failure("Groq","example",kind="server")
        self.assertEqual(scheduler.state("Groq","example").consecutive_failures,3)

if __name__=="__main__":
    unittest.main()

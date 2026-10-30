"""Safety invariants for protocol, evidence, scheduling and evaluation."""
import asyncio
import unittest
from council.protocol import Act, Message
from council.bus import ThreadBus
from council.evidence import polarity_ok
from council.models import Claim, ClaimLedger, Evidence, EvidenceKind
from council.quota import TokenBucket, CircuitBreaker
from council.verify.mutation import numeric_mutants, discriminates
from eval.baseline import best_of_n, self_consistency
from eval.metrics import bootstrap_ci

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.ledger = ClaimLedger()
        self.ledger.add_claim(Claim("c1", 1, "Claim", "gpt-oss"))
        self.ledger.add_claim(Claim("c2", 1, "Other", "command"))
        self.ledger.attach(Evidence("pass", "c1", 1, EvidenceKind.TEST, "pass",
                                    "scoped", "hash", independently_checked=True))
        self.ledger.attach(Evidence("fail", "c1", 1, EvidenceKind.TEST, "fail",
                                    "scoped", "hash2", independently_checked=True))
        self.ledger.attach(Evidence("review", "c1", 1, EvidenceKind.MODEL_REVIEW, "fail",
                                    "opinion", "hash3"))
    def msg(self, act, refs=(), thread="c1"):
        return Message("m1", thread, act, "agent-1", "content", tuple(refs))
    def test_polarity(self):
        self.assertTrue(polarity_ok(self.msg(Act.DEFEND, ("pass",)), self.ledger))
        self.assertFalse(polarity_ok(self.msg(Act.DEFEND, ("fail",)), self.ledger))
        self.assertFalse(polarity_ok(self.msg(Act.DEFEND, ("pass",)), self.ledger,
                                     thread_refs=frozenset({"pass"})))
        self.assertTrue(polarity_ok(self.msg(Act.CHALLENGE, ("fail",)), self.ledger))
        self.assertFalse(polarity_ok(self.msg(Act.CHALLENGE, ("review",)), self.ledger))
        self.assertTrue(polarity_ok(self.msg(Act.CONCEDE, ("fail",)), self.ledger))
        self.assertFalse(polarity_ok(self.msg(Act.CONCEDE, ("fail",)), self.ledger,
                                      owner_last_refs=frozenset({"fail"})))
        self.assertFalse(polarity_ok(self.msg(Act.CONCEDE, ("pass",)), self.ledger))
        self.assertFalse(polarity_ok(self.msg(Act.DEFEND, ("pass",), "c2"), self.ledger))
        self.assertFalse(polarity_ok(self.msg(Act.CHALLENGE, ("unknown",)), self.ledger))
    def test_bus_scope_caps_and_deduplication(self):
        bus = ThreadBus(max_messages=2)
        a = self.msg(Act.PROPOSE)
        self.assertTrue(bus.deliver(a))
        self.assertFalse(bus.deliver(a))
        self.assertTrue(bus.deliver(Message("m2", "c1", Act.ASK, "agent-2", "Why?")))
        self.assertFalse(bus.deliver(Message("m3", "c1", Act.ANSWER, "agent-1", "Because")))
        with self.assertRaises(PermissionError):
            bus.view("c1", "outsider", allowed={"agent-1"})
        self.assertEqual(len(bus.view("c1", "agent-1", allowed={"agent-1"})), 2)
    def test_invalid_messages(self):
        with self.assertRaises(ValueError):
            Message("", "c", Act.ASK, "a", "hi")
        with self.assertRaises(ValueError):
            Message("m", "c", Act.ASK, "a", "a"*2401)

class VerificationTests(unittest.TestCase):
    def test_mutants_and_discrimination(self):
        self.assertTrue(numeric_mutants("156"))
        self.assertTrue(discriminates(lambda s: "pass" if s == "156" else "fail",
                                      "156", numeric_mutants("156")))
        self.assertFalse(discriminates(lambda s: "pass", "156", numeric_mutants("156")))
        self.assertFalse(discriminates(lambda s: "error" if s != "156" else "pass",
                                       "156", numeric_mutants("156")))
        self.assertFalse(discriminates(lambda s: "pass", "abc", []))
    def test_baselines(self):
        self.assertEqual(self_consistency(["b","a","a"]), "a")
        self.assertEqual(best_of_n(["a","bbb","cc"], len), "bbb")
        with self.assertRaises(ValueError):
            best_of_n([], len)
    def test_bootstrap(self):
        mean, lo, hi = bootstrap_ci([1.0, 2.0, 3.0], n=200, seed=13)
        self.assertEqual(mean, 2)
        self.assertLessEqual(lo, mean)
        self.assertGreaterEqual(hi, mean)
        self.assertEqual(bootstrap_ci([1.0,2.0,3.0],n=200,seed=13),
                         (mean,lo,hi))

class QuotaTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifo_budget(self):
        import time
        bucket = TokenBucket(60, 1)
        self.assertTrue(await bucket.acquire(time.monotonic()+1))
        self.assertFalse(await bucket.acquire(time.monotonic()+0.01))
        bucket.observe_headers({"X-RateLimit-Remaining-Requests":"0"})
        self.assertEqual(bucket.tokens, 0)
    async def test_circuit_breaker(self):
        cb = CircuitBreaker(3)
        for _ in range(3):
            cb.record_failure("x", cooldown=100)
        self.assertFalse(cb.available("x"))
        cb.record_probe_success("x")
        self.assertTrue(cb.available("x"))

if __name__ == "__main__":
    unittest.main()

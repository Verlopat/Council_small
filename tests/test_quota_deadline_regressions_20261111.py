"""Offline regressions for shared quotas, accounting and elapsed deadlines."""
import asyncio
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from council.budget import RunBudget
from council.quota import EndpointState, QuotaContention, QuotaScheduler
from council.transport import FamilyTransport, FamilyUnavailable


class QuotaRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_midnight_resets_account_once_across_models(self):
        q = QuotaScheduler(default_rate=600, default_burst=10)
        for model in ('a', 'b'):
            q.state('provider', model).day = (
                datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        q.shared_daily['provider'] = 1
        q.shared_daily_tokens['provider'] = 10
        await q.acquire('provider', 'a', deadline=time.monotonic()+1,
                        expected_tokens=10)
        with self.assertRaises(QuotaContention):
            await q.acquire('provider', 'b', deadline=time.monotonic()+1)
        self.assertEqual(q.shared_usage['provider'], 1)
        self.assertEqual(q.shared_used_tokens['provider'], 10)

    async def test_queued_lock_obeys_deadline_and_remains_usable(self):
        q = QuotaScheduler()
        await q.locks['provider'].acquire()
        started = time.monotonic()
        try:
            with self.assertRaises(QuotaContention):
                await asyncio.wait_for(q.acquire('provider', 'a',
                    deadline=started+.02), .5)
            self.assertLess(time.monotonic()-started, .4)
            self.assertTrue(q.locks['provider'].locked())
        finally:
            q.locks['provider'].release()
        await q.acquire('provider', 'a', deadline=time.monotonic()+1)
        self.assertFalse(q.locks['provider'].locked())

    async def test_partial_usage_does_not_double_count_reservation(self):
        q = QuotaScheduler(default_burst=10)
        await q.acquire('provider', 'a', deadline=time.monotonic()+1,
                        expected_tokens=100)
        q.observe('provider', 'a', {}, input_tokens=20)
        self.assertEqual(q.shared_used_tokens['provider'], 100)
        q.observe('provider', 'a', {}, input_tokens=20, output_tokens=30,
                  reserved_tokens=100)
        self.assertEqual(q.shared_used_tokens['provider'], 50)
        self.assertEqual(q.state('provider', 'a').tokens_today, 50)

    async def test_tpm_overage_is_retained_as_debt(self):
        q = QuotaScheduler()
        q.configure('provider', 'a', rate_per_minute=600, burst=10,
                    tokens_per_minute=100)
        await q.acquire('provider', 'a', deadline=time.monotonic()+1,
                        expected_tokens=100)
        q.observe('provider', 'a', {}, input_tokens=150, output_tokens=50,
                  reserved_tokens=100)
        self.assertEqual(q.shared_tpm_available['provider'], -100)
        with self.assertRaises(QuotaContention):
            await q.acquire('provider', 'a', deadline=time.monotonic()+.1,
                            expected_tokens=1)

    def test_invalid_caps_rejected(self):
        for kwargs in ({'rate_per_minute':math.nan},
                       {'rate_per_minute':math.inf}, {'burst':1.5},
                       {'daily_requests':-1}, {'daily_tokens':2.5},
                       {'tokens_per_minute':True}):
            options = dict(rate_per_minute=30, burst=1)
            options.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                EndpointState(**options)


class TransportDeadlineRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_quota_wait_cannot_extend_call_timeout(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(
                os.environ, {'GROQ_API_KEY':'dummy'}):
            transport = FamilyTransport(timeout=2, strict_timeout=True,
                health_file=Path(folder)/'health.json')
            class SlowQuota:
                async def acquire(self, *args, **kwargs):
                    await asyncio.sleep(.02)
                def failure(self, *args, **kwargs):
                    pass
            transport.quota = SlowQuota()
            transport.router.expand = lambda candidate, seen: [candidate]
            calls = []
            transport.router.generate = lambda *args, **kwargs: calls.append(kwargs) or 'ok'
            # A deterministic clock advance models queue consumption of the
            # full timeout without making this regression take seconds.
            real_clock = time.monotonic
            started = real_clock()
            def clock():
                elapsed = real_clock()-started
                return real_clock() + (3 if elapsed >= .01 else 0)
            with patch('council.transport.time.monotonic', side_effect=clock):
                with self.assertRaises(FamilyUnavailable):
                    await transport.complete('gpt-oss', 'q',
                        RunBudget.start(30, reserve=0), role='proposal')
            self.assertEqual(calls, [])


class EvaluationAccountingRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_failed_and_retried_baseline_requests_count_toward_budget(self):
        from eval.execute import run_task
        from council.transport import CallResult
        class Events:
            def __init__(self):
                self.rows = []
            def replay(self):
                return self.rows
            def add(self, kind):
                self.rows.append({'event':kind})
        events = Events()
        class Council:
            def __init__(self, *args, **kwargs):
                pass
            async def run(self, question):
                for kind in ('model_call_started', 'model_call_retry',
                             'model_call_started', 'model_call_started'):
                    events.add(kind)
                return {'research_result':{}, 'verdict':{}, 'composition':{}}
        class Transport:
            calls = 0
            async def complete(self, family, message, budget, **kwargs):
                self.calls += 1
                events.add('model_call_started')
                if self.calls == 1:
                    events.add('model_call_retry')
                    return CallResult(family, 'mock', 'mock', '42', 0, 'hash')
                raise FamilyUnavailable(family, ['timeout'])
        with patch('eval.execute.FullCouncilRunner', Council):
            rows = await run_task({'id':'x', 'prompt':'6*7', 'expected':'42'},
                Transport(), events, deadline=20, baseline_samples=2,
                skip_vote6=True)
        council, baseline, single = rows
        self.assertEqual(council['calls'], 4)
        self.assertEqual(baseline['calls'], 3)
        self.assertFalse(baseline['equal_budget'])
        self.assertEqual(single['calls'], 2)
        self.assertFalse(single['equal_budget'])

    def test_nonfinite_budget_rejected(self):
        for seconds, reserve in ((math.nan, 1), (math.inf, 1), (10, math.nan)):
            with self.subTest(seconds=seconds, reserve=reserve):
                with self.assertRaises(ValueError):
                    RunBudget.start(seconds, reserve)


class RetryRecordingRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_retry_denied_by_quota_is_not_counted_as_sent(self):
        from router_errors import CandidateError
        records = []
        class Quota:
            n = 0
            async def acquire(self, *args, **kwargs):
                self.n += 1
                if self.n == 2:
                    raise QuotaContention('exhausted')
            def failure(self, *args, **kwargs):
                pass
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,
                {'GROQ_API_KEY':'dummy', 'COUNCIL_HARD_DEADLINE':'0'}):
            transport = FamilyTransport(health_file=Path(folder)/'health.json',
                record=lambda event_type, **kwargs: records.append(event_type))
            transport.quota = Quota()
            transport.router.expand = lambda candidate, seen: [candidate]
            def truncated(*args, **kwargs):
                raise CandidateError('truncated', kind='output_truncated')
            transport.router.generate = truncated
            with self.assertRaises(FamilyUnavailable):
                await transport.complete('gpt-oss', 'q',
                    RunBudget.start(20, reserve=0), role='proposal')
        self.assertEqual(records.count('model_call_started'), 1)
        self.assertEqual(records.count('model_call_retry'), 0)

    def test_config_rejects_fractional_burst_and_nonfinite_rate(self):
        from council.config import load_config
        original = Path('council.yaml').read_text()
        import yaml
        for detail in ({'requests_per_minute':float('nan')},
                       {'requests_per_minute':30, 'burst':1.5}):
            config = yaml.safe_load(original)
            config['rate_limits'] = {'Groq':detail}
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'config.yaml'
                path.write_text(yaml.safe_dump(config))
                with self.subTest(detail=detail), self.assertRaises(ValueError):
                    load_config(path)

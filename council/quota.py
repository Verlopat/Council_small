"""FIFO endpoint quotas, shared account budgets and failure circuit breakers."""
from __future__ import annotations
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from router_errors import retry_after_seconds

class QuotaContention(TimeoutError):
    pass

@dataclass
class EndpointState:
    rate_per_minute: float
    burst: int
    daily_requests: int | None = None
    daily_tokens: int | None = None
    remaining: float = 0
    refreshed_at: float = 0
    day: str = ""
    requests_today: int = 0
    tokens_today: int = 0
    consecutive_failures: int = 0
    cooldown_until: float = 0

    def __post_init__(self):
        if self.rate_per_minute <= 0 or self.burst <= 0:
            raise ValueError("Quota rate and burst must be positive")
        self.remaining = float(self.burst)
        self.refreshed_at = time.monotonic()
        self.day = datetime.now(timezone.utc).date().isoformat()

class QuotaScheduler:
    """One FIFO lock per provider, token bucket per endpoint, shared provider budgets.

    Configured quotas are *user-supplied*; defaults must not be treated as provider limits.
    """
    def __init__(self, *, default_rate: float = 1.0, default_burst: int = 1):
        self.default_rate, self.default_burst = default_rate, default_burst
        self.states: dict[tuple[str, str], EndpointState] = {}
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.shared_daily: dict[str, int] = {}
        self.shared_usage: dict[str, int] = defaultdict(int)
        self.shared_daily_tokens: dict[str,int] = {}
        self.shared_used_tokens: dict[str,int] = defaultdict(int)

    def configure(self, provider: str, model: str, *, rate_per_minute: float,
                  burst: int = 1, daily_requests: int | None = None,
                  daily_tokens: int | None = None):
        self.states[(provider, model)] = EndpointState(
            rate_per_minute, burst, daily_requests, daily_tokens)

    def state(self, provider: str, model: str) -> EndpointState:
        return self.states.setdefault((provider, model), EndpointState(
            self.default_rate, self.default_burst))

    async def acquire(self, provider: str, model: str, *, deadline: float,
                      expected_tokens: int = 0) -> None:
        if expected_tokens < 0:
            raise ValueError("Token estimate must be non-negative")
        # Holding a provider lock while sleeping gives FIFO access for that provider.
        async with self.locks[provider]:
            state = self.state(provider, model)
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise QuotaContention("Global deadline reached in provider queue")
                today = datetime.now(timezone.utc).date().isoformat()
                if today != state.day:
                    state.day, state.requests_today, state.tokens_today = today, 0, 0
                    self.shared_usage[provider] = 0
                    self.shared_used_tokens[provider] = 0
                if state.consecutive_failures >= 3 and state.cooldown_until > now:
                    raise QuotaContention("Provider circuit breaker open")
                if state.daily_requests is not None and state.requests_today >= state.daily_requests:
                    raise QuotaContention("Daily request allowance exhausted")
                if (state.daily_tokens is not None and
                    state.tokens_today + expected_tokens > state.daily_tokens):
                    raise QuotaContention("Daily token allowance exhausted")
                if (provider in self.shared_daily and
                    self.shared_usage[provider] >= self.shared_daily[provider]):
                    raise QuotaContention("Shared account allowance exhausted")
                if (provider in self.shared_daily_tokens and
                    self.shared_used_tokens[provider] + expected_tokens >
                    self.shared_daily_tokens[provider]):
                    raise QuotaContention("Shared account token allowance exhausted")
                state.remaining = min(state.burst,
                    state.remaining + (now - state.refreshed_at) * state.rate_per_minute / 60)
                state.refreshed_at = now
                cooldown = max(0.0, state.cooldown_until - now)
                wait_tokens = max(0.0, 1.0 - state.remaining) * 60 / state.rate_per_minute
                wait = max(cooldown, wait_tokens)
                if wait <= 0:
                    state.remaining -= 1
                    state.requests_today += 1
                    state.tokens_today += expected_tokens
                    self.shared_usage[provider] += 1
                    self.shared_used_tokens[provider] += expected_tokens
                    return
                if now + wait >= deadline:
                    raise QuotaContention("No quota can arrive before request deadline")
                await asyncio.sleep(min(wait, deadline - now))

    def observe(self, provider: str, model: str, headers: dict,
                *, input_tokens: int | None = None,
                output_tokens: int | None = None,
                reserved_tokens: int = 0) -> None:
        state = self.state(provider, model)
        lowered = {str(k).lower(): str(v) for k, v in headers.items()}
        remaining = lowered.get("x-ratelimit-remaining-requests")
        if remaining is not None:
            try:
                state.remaining = min(state.remaining, max(0, float(remaining)))
            except ValueError:
                pass
        if input_tokens is not None or output_tokens is not None:
            # Reconcile with estimate separately at the caller; this is
            # authoritative observed usage, not an inferred token count.
            observed = max(0,int(input_tokens or 0)) + max(0,int(output_tokens or 0))
            delta = observed - max(0,reserved_tokens)
            state.tokens_today = max(0,state.tokens_today + delta)
            self.shared_used_tokens[provider] = max(0,
                self.shared_used_tokens[provider] + delta)
        ra = retry_after_seconds(lowered.get("retry-after"))
        if ra is not None and ra > 0:
            state.cooldown_until = max(state.cooldown_until, time.monotonic() + ra)

    def failure(self, provider: str, model: str, *, kind: str,
                retry_after: float | None = None) -> None:
        # Local scheduling exhaustion, prompt length and rejected client input
        # are not evidence that the provider endpoint is unhealthy.
        if kind in {"quota_contention", "context_length", "request_invalid"}:
            return
        state = self.state(provider, model)
        state.consecutive_failures += 1
        delay = retry_after if retry_after is not None else min(60.0, 2.0 ** state.consecutive_failures)
        if kind == "billing_required":
            state.cooldown_until = time.monotonic() + 86400.0
        elif kind in {"rate_limit", "auth"} or state.consecutive_failures >= 3:
            state.cooldown_until = time.monotonic() + min(86400.0, max(1.0, delay))

    def success(self, provider: str, model: str) -> None:
        state = self.state(provider, model)
        state.consecutive_failures = 0
        state.cooldown_until = 0.0

"""FIFO endpoint quotas, shared account budgets and failure circuit breakers."""
from __future__ import annotations
import asyncio
import math
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
    tokens_per_minute: int | None = None
    remaining: float = 0
    refreshed_at: float = 0
    day: str = ""
    requests_today: int = 0
    tokens_today: int = 0
    consecutive_failures: int = 0
    cooldown_until: float = 0

    def __post_init__(self):
        if (not math.isfinite(self.rate_per_minute) or self.rate_per_minute <= 0
                or type(self.burst) is not int or self.burst <= 0 or
                self.tokens_per_minute is not None
                and self.tokens_per_minute <= 0):
            raise ValueError("Quota rates and burst must be positive")
        for cap in (self.daily_requests, self.daily_tokens, self.tokens_per_minute):
            if cap is not None and (type(cap) is not int or cap <= 0):
                raise ValueError("Quota caps must be positive integers")
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
        self.provider_states: dict[str, EndpointState] = {}
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.shared_day: dict[str, str] = {}
        self.shared_daily: dict[str, int] = {}
        self.shared_usage: dict[str, int] = defaultdict(int)
        self.shared_daily_tokens: dict[str,int] = {}
        self.shared_used_tokens: dict[str,int] = defaultdict(int)
        # Actual tokens/minute allowances are account/provider-scoped,
        # not independently refillable per model endpoint.
        self.shared_tpm_cap: dict[str,int] = {}
        self.shared_tpm_available: dict[str,float] = {}
        self.shared_tpm_updated: dict[str,float] = {}

    def configure(self, provider: str, model: str, *, rate_per_minute: float,
                  burst: int = 1, daily_requests: int | None = None,
                  daily_tokens: int | None = None,
                  tokens_per_minute: int | None = None):
        self.states[(provider, model)] = EndpointState(
            rate_per_minute, burst, daily_requests, daily_tokens,
            tokens_per_minute)
        # The first configured account budget is shared across every endpoint.
        # Repeated per-model configuration must NOT reset refill/usage.
        self.provider_states.setdefault(provider, EndpointState(
            rate_per_minute, burst))
        if daily_requests is not None:
            self.shared_daily[provider] = daily_requests
        if daily_tokens is not None:
            self.shared_daily_tokens[provider] = daily_tokens
        if tokens_per_minute is not None:
            if type(tokens_per_minute) is not int or tokens_per_minute <= 0:
                raise ValueError("tokens_per_minute must be positive integer")
            self.shared_tpm_cap[provider]=tokens_per_minute
            self.shared_tpm_available.setdefault(provider,float(tokens_per_minute))
            self.shared_tpm_updated.setdefault(provider,time.monotonic())

    def configure_provider(self, provider: str, *, rate_per_minute: float,
                           burst: int = 1, daily_requests: int | None = None,
                           daily_tokens: int | None = None,
                           tokens_per_minute: int | None = None) -> None:
        """Configure one account-wide bucket, not an independent bucket per model."""
        self.configure(provider, "__provider_config__", rate_per_minute=rate_per_minute,
                       burst=burst, daily_requests=daily_requests,
                       daily_tokens=daily_tokens, tokens_per_minute=tokens_per_minute)

    def state(self, provider: str, model: str) -> EndpointState:
        return self.states.setdefault((provider, model), EndpointState(
            self.default_rate, self.default_burst))

    async def acquire(self, provider: str, model: str, *, deadline: float,
                      expected_tokens: int = 0) -> None:
        if expected_tokens < 0:
            raise ValueError("Token estimate must be non-negative")
        if not math.isfinite(deadline):
            raise ValueError("Deadline must be finite")
        # Queueing itself consumes the deadline, even behind a long-lived call.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QuotaContention("Global deadline reached in provider queue")
        try:
            await asyncio.wait_for(self.locks[provider].acquire(), remaining)
        except TimeoutError:
            raise QuotaContention("Global deadline reached in provider queue") from None
        try:
            state = self.state(provider, model)
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise QuotaContention("Global deadline reached in provider queue")
                today = datetime.now(timezone.utc).date().isoformat()
                if today != state.day:
                    state.day, state.requests_today, state.tokens_today = today, 0, 0
                # Reset shared counters once per account/day, not once for
                # every endpoint first visited after midnight.
                if self.shared_day.get(provider) != today:
                    self.shared_day[provider] = today
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
                account = self.provider_states.get(provider)
                if account is not None:
                    account.remaining = min(
                        account.burst,
                        account.remaining + max(0.0, now - account.refreshed_at)
                        * account.rate_per_minute / 60.0)
                    account.refreshed_at = now
                    wait = max(wait, max(0.0, 1.0 - account.remaining)
                               * 60.0 / account.rate_per_minute)
                cap=self.shared_tpm_cap.get(provider)
                if cap is not None:
                    if expected_tokens > cap:
                        raise QuotaContention(
                            "Estimated request exceeds configured provider TPM cap")
                    last=self.shared_tpm_updated[provider]
                    tokens=min(float(cap),
                               self.shared_tpm_available[provider]+
                               max(0,now-last)*cap/60.0)
                    self.shared_tpm_available[provider]=tokens
                    self.shared_tpm_updated[provider]=now
                    wait=max(wait,max(0.0,expected_tokens-tokens)*60.0/cap)
                if wait <= 0:
                    state.remaining -= 1
                    if account is not None:
                        account.remaining -= 1
                    if cap is not None:
                        self.shared_tpm_available[provider]-=expected_tokens
                    state.requests_today += 1
                    state.tokens_today += expected_tokens
                    self.shared_usage[provider] += 1
                    self.shared_used_tokens[provider] += expected_tokens
                    return
                if now + wait >= deadline:
                    raise QuotaContention("No quota can arrive before request deadline")
                await asyncio.sleep(min(wait, deadline - now))

        finally:
            self.locks[provider].release()

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
                if provider in self.provider_states:
                    account = self.provider_states[provider]
                    account.remaining = min(account.remaining,
                                            max(0, float(remaining)))
            except ValueError:
                pass
        if input_tokens is not None and output_tokens is not None:
            # Reconcile with estimate separately at the caller; this is
            # authoritative observed usage, not an inferred token count.
            observed = max(0,int(input_tokens or 0)) + max(0,int(output_tokens or 0))
            delta = observed - max(0,reserved_tokens)
            state.tokens_today = max(0,state.tokens_today + delta)
            self.shared_used_tokens[provider] = max(0,
                self.shared_used_tokens[provider] + delta)
            if provider in self.shared_tpm_cap:
                cap=self.shared_tpm_cap[provider]
                self.shared_tpm_available[provider]=min(float(cap),
                    self.shared_tpm_available[provider]-delta)
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

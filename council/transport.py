"""Thin family-aware adapter over the tested Verlopat/test model_router.

The upstream API currently exposes normalized text, not raw provider response
JSON/headers. Calls are tracked honestly as text-only until raw transport exists.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
import time
from pathlib import Path

from model_router import Candidate, KEY_NAMES, Router, RAW_CAPTURE, redacted
from router_errors import CandidateError
from router_health import HealthCache
from council.budget import RunBudget
from council.families import endpoint_list
from council.quota import QuotaScheduler, QuotaContention

class FamilyUnavailable(RuntimeError):
    def __init__(self, family: str, failures: list[str]):
        self.family = family
        self.failures = failures
        super().__init__(family + ": no eligible endpoint succeeded")

@dataclass(frozen=True)
class CallResult:
    family: str
    provider: str
    model: str
    text: str
    seconds: float
    prompt_hash: str
    raw: dict | None = None
    headers: dict | None = None
    status: int | None = None

class FamilyTransport:
    def __init__(self, *, timeout: float = 28.0, health_file: Path | None = None,
                 record=None):
        self.timeout = timeout
        self.router = Router(timeout=timeout)
        self.cache = HealthCache(health_file or Path(".router_health.json"))
        self.record = record or (lambda *a, **k: None)
        self.quota = QuotaScheduler(default_rate=600, default_burst=1)
        # Provider limits are user-confirmed settings, not guessed quotas.
        try:
            configured = json.loads(os.getenv('COUNCIL_LIMITS_JSON', '{}'))
            for provider, settings in configured.items():
                if isinstance(settings, dict) and 'shared_daily_requests' in settings:
                    self.quota.shared_daily[provider] = int(settings['shared_daily_requests'])
                if isinstance(settings, dict) and 'shared_daily_tokens' in settings:
                    self.quota.shared_daily_tokens[provider] = int(settings['shared_daily_tokens'])
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Invalid COUNCIL_LIMITS_JSON')

    @staticmethod
    def _eligible(provider: str) -> bool:
        # A key does not prove a free allowance. Restrict risky providers to
        # user-confirmed free modes; all other entries are a fixed allowlist.
        if provider == "Cohere" and os.getenv("COHERE_TRIAL_CONFIRMED") != "1":
            return False
        if provider == "Ollama Cloud" and os.getenv("OLLAMA_FREE_CONFIRMED") != "1":
            return False
        key = KEY_NAMES.get(provider)
        return bool(key and os.getenv(key, "").strip())

    async def complete(self, family: str, message: str, budget: RunBudget, *,
                       role: str, synthesis: bool = False) -> CallResult:
        failures = []
        seen: set[tuple[str, str]] = set()
        for entry in endpoint_list(family):
            if not self._eligible(entry.provider):
                failures.append(entry.provider + ": unconfigured or free mode unconfirmed")
                continue
            if self.cache.blocked(entry.provider, entry.model):
                failures.append(entry.provider + "/" + entry.model + ": cooldown")
                continue
            allowed = budget.allowed(self.timeout, synthesis=synthesis)
            if allowed <= 1:
                raise FamilyUnavailable(family, failures + ["deadline"])
            candidate = Candidate(entry.provider, entry.model)
            estimated_tokens=max(1,len(message)//3)+1800
            try:
                await self.quota.acquire(entry.provider, entry.model,
                    deadline=time.monotonic() + allowed,
                    expected_tokens=estimated_tokens)
                # Same allowlist/catalog safeguards as the original router.
                options = await asyncio.wait_for(
                    asyncio.to_thread(self.router.expand, candidate, seen),
                    timeout=allowed)
                if not options or options[0].model != entry.model:
                    raise CandidateError("Model not in permitted catalog", kind="model_unavailable")
                seen.add((entry.provider, entry.model))
                t0 = time.monotonic()
                timeout = min(allowed, budget.allowed(self.timeout, synthesis=synthesis))
                if timeout <= 1:
                    raise TimeoutError()
                sep = chr(10) + 'DATA_JSON:' + chr(10)
                system_text, user_text = (message.split(sep, 1)
                    if message.startswith('SYSTEM ROLE:') and sep in message
                    else (None, message))
                self.record("model_call_started", role=role, family=family,
                            provider=entry.provider, model=entry.model,
                            prompt_hash=hashlib.sha256(message.encode()).hexdigest())
                def infer():
                    if os.getenv("COUNCIL_HARD_DEADLINE", "0") == "1":
                        from council.process_infer import generate as generate_process
                        return generate_process(
                            entry.provider, entry.model, user_text,
                            system_text=system_text, timeout=timeout,
                            max_tokens=1800)
                    captured = []
                    token = RAW_CAPTURE.set(captured)
                    try:
                        opts = dict(probe=False, request_timeout=max(0.5, timeout - 0.5),
                                    max_output_tokens=1800)
                        if system_text:
                            opts['system_text'] = system_text
                        answer = self.router.generate(candidate, user_text, **opts)
                        return answer, (captured[-1] if captured else None)
                    finally:
                        RAW_CAPTURE.reset(token)
                text, raw = await asyncio.wait_for(asyncio.to_thread(infer), timeout=timeout)
                if not text.strip():
                    raise CandidateError("Empty response", kind="invalid_response")
                elapsed = time.monotonic() - t0
                self.cache.success(entry.provider, entry.model)
                self.quota.success(entry.provider, entry.model)
                usage = (raw.get('body',{}).get('usage',{})
                         if raw and isinstance(raw.get('body'),dict) else {})
                if not usage and raw and isinstance(raw.get('body'),dict):
                    usage=raw['body'].get('usageMetadata',{})
                if not isinstance(usage,dict):usage={}
                used_input = usage.get('prompt_tokens',usage.get('promptTokenCount'))
                used_output = usage.get('completion_tokens',usage.get('candidatesTokenCount'))
                if raw:
                    self.quota.observe(entry.provider, entry.model,
                        raw.get('headers', {}), input_tokens=used_input,
                        output_tokens=used_output,
                        reserved_tokens=estimated_tokens if used_input is not None
                                          and used_output is not None else 0)
                self.record("model_call_succeeded", role=role, family=family,
                            provider=entry.provider, model=entry.model,
                            seconds=elapsed, response=text,
                            prompt_hash=hashlib.sha256(message.encode()).hexdigest(),
                            status=raw.get('status') if raw else None,
                            headers=raw.get('headers') if raw else {},
                            raw_body=raw.get('body') if raw else None,
                            input_tokens=used_input,output_tokens=used_output,
                            reported_model=(raw.get('body',{}).get('model')
                                if raw and isinstance(raw.get('body'),dict) else None))
                return CallResult(family, entry.provider, entry.model, text, elapsed,
                                  hashlib.sha256(message.encode()).hexdigest(),
                                  raw.get('body') if raw else None,
                                  raw.get('headers') if raw else {},
                                  raw.get('status') if raw else None)
            except QuotaContention:
                kind = 'quota_contention'
            except (asyncio.TimeoutError, TimeoutError):
                kind = "timeout"
            except CandidateError as exc:
                kind = exc.kind
            except (KeyError, TypeError, ValueError):
                kind = "invalid_response"
            # No underlying exception content, URLs or keys are persisted.
            self.cache.failure(entry.provider, entry.model, kind)
            self.quota.failure(entry.provider, entry.model, kind=kind)
            failures.append(entry.provider + "/" + entry.model + ": " + kind)
            self.record("model_call_failed", role=role, family=family,
                        provider=entry.provider, model=entry.model, kind=kind)
            if budget.allowed(self.timeout, synthesis=synthesis) <= 1:
                break
        raise FamilyUnavailable(family, failures)

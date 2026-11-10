"""Thin family-aware adapter over the tested Verlopat/test model_router.

The upstream API currently exposes normalized text, not raw provider response
JSON/headers. Calls are tracked honestly as text-only until raw transport exists.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
import os
import time
from pathlib import Path

from model_router import Candidate, KEY_NAMES, Router, RAW_CAPTURE, redacted
from router_errors import CandidateError
from router_health import HealthCache
from council.budget import RunBudget
from council.families import endpoint_list
from council.structured import response_format as model_response_format
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
                 record=None, strict_timeout: bool = False):
        if timeout<=1 or not math.isfinite(timeout):
            raise ValueError("timeout must be finite and greater than 1 second")
        self.timeout = timeout
        self.strict_timeout=bool(strict_timeout)
        self.router = Router(timeout=timeout)
        self.cache = HealthCache(health_file or Path(".router_health.json"))
        self.record = record or (lambda *a, **k: None)
        # Gentle unconfigured pacing (30 RPM/account) is a protective
        # floor, NOT a claim about any provider's free-tier allowance.
        # Real RPM/TPM caps must be configured from provider dashboards.
        try:
            safe_rpm=float(os.getenv("COUNCIL_UNCONFIGURED_RPM","30"))
        except ValueError:
            raise ValueError("COUNCIL_UNCONFIGURED_RPM must be numeric") from None
        if not 1 <= safe_rpm <= 600:
            raise ValueError("COUNCIL_UNCONFIGURED_RPM must be 1..600")
        self.quota = QuotaScheduler(default_rate=safe_rpm, default_burst=1)
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
            # With an explicit CLI timeout, do not silently extend the
            # request to a provider's longer preferred endpoint timeout.
            endpoint_timeout=(self.timeout if self.strict_timeout else
                              max(self.timeout,entry.timeout_seconds or 0))
            if not self._eligible(entry.provider):
                failures.append(entry.provider + ": unconfigured or free mode unconfirmed")
                continue
            if self.cache.blocked(entry.provider, entry.model):
                failures.append(entry.provider + "/" + entry.model + ": cooldown")
                continue
            allowed = budget.allowed(endpoint_timeout, synthesis=synthesis)
            if allowed <= 1:
                raise FamilyUnavailable(family, failures + ["deadline"])
            candidate = Candidate(entry.provider, entry.model)
            # Opt-in larger translator output allowance when a reasoning
            # provider truncates responses. Default stays quota-conservative.
            if role == "translate":
                try:
                    output_tokens=int(os.getenv(
                        "COUNCIL_TRANSLATOR_MAX_TOKENS", "1800"))
                except ValueError:
                    raise ValueError(
                        "COUNCIL_TRANSLATOR_MAX_TOKENS must be an integer") from None
                if not 256 <= output_tokens <= 8192:
                    raise ValueError(
                        "COUNCIL_TRANSLATOR_MAX_TOKENS must be 256..8192")
            else:
                role_tokens = {"proposal": 2800, "review": 3000,
                               "revision": 3500, "repair": 2500,
                               "topic_judge": 2100}
                output_tokens = role_tokens.get(role, 1800)
            if entry.max_tokens is not None:
                output_tokens = max(output_tokens, entry.max_tokens)
            # Cohere's long strict-schema proposals repeatedly truncated
            # despite 6000 tokens. With compact source inputs and at most 5
            # claims, default to a smaller output cap. Other Cohere roles
            # retain the higher 6000-token endpoint limit.
            if entry.provider=="Cohere" and role=="proposal":
                try:
                    cap=int(os.getenv("COUNCIL_COHERE_PROPOSAL_MAX_TOKENS","3500"))
                except ValueError:
                    raise ValueError(
                        "COUNCIL_COHERE_PROPOSAL_MAX_TOKENS must be an integer") from None
                if not 2000<=cap<=6000:
                    raise ValueError(
                        "COUNCIL_COHERE_PROPOSAL_MAX_TOKENS must be 2000..6000")
                output_tokens=min(output_tokens,cap)
            estimated_tokens=max(1,len(message)//3)+output_tokens
            retry_after = None
            http_status = None
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
                timeout = min(allowed, budget.allowed(endpoint_timeout, synthesis=synthesis))
                if timeout <= 1:
                    raise TimeoutError()
                sep = chr(10) + 'DATA_JSON:' + chr(10)
                system_text, user_text = (message.split(sep, 1)
                    if message.startswith('SYSTEM ROLE:') and sep in message
                    else (None, message))
                formatting = model_response_format(entry.provider, entry.model, role)
                http_status = None
                self.record("model_call_started", role=role, family=family,
                            provider=entry.provider, model=entry.model,
                            prompt_hash=hashlib.sha256(message.encode()).hexdigest())
                def infer():
                    if os.getenv("COUNCIL_HARD_DEADLINE", "0") == "1":
                        from council.process_infer import generate as generate_process
                        return generate_process(
                            entry.provider, entry.model, user_text,
                            system_text=system_text, timeout=timeout,
                            max_tokens=output_tokens, response_format=formatting)
                    captured = []
                    token = RAW_CAPTURE.set(captured)
                    try:
                        opts = dict(probe=False, request_timeout=max(0.5, timeout - 0.5),
                                    max_output_tokens=output_tokens,
                                    response_format=formatting)
                        if system_text:
                            opts['system_text'] = system_text
                        answer = self.router.generate(candidate, user_text, **opts)
                        return answer, (captured[-1] if captured else None)
                    finally:
                        RAW_CAPTURE.reset(token)
                # One retry only after a *completed* provider request raises
                # CandidateError. An asyncio.wait_for thread cancellation may
                # leave a request running and must never trigger a duplicate.
                for attempt_no in range(2):
                    try:
                        text, raw = await asyncio.wait_for(
                            asyncio.to_thread(infer), timeout=timeout)
                        break
                    except CandidateError as exc:
                        transient=exc.kind in {"timeout", "server", "connection"}
                        truncated=(exc.kind=="output_truncated" and
                                   role in {"proposal","repair","extract",
                                            "review","revision","hunter"} and
                                   output_tokens < 16384)
                        if attempt_no or not (transient or truncated):
                            raise
                        delay=(4.0 if exc.kind=="server"
                               else 2.0 if exc.kind=="connection"
                               else 0.5 if exc.kind=="timeout" else 0.25)
                        remaining=budget.allowed(endpoint_timeout,
                                                 synthesis=synthesis)
                        if remaining <= delay+6:
                            raise
                        if truncated:
                            output_tokens=min(16384,output_tokens*2)
                        elif (exc.kind=="server" and role=="judge"
                              and entry.provider=="Gemini"
                              and formatting is not None):
                            # A schema-triggered 5xx is possible but NOT
                            # established; one plain-JSON retry distinguishes
                            # this from an endpoint outage without logging
                            # response bodies or confidential model content.
                            formatting=None
                        safe_status=None
                        try:
                            import re
                            matched=re.match(r"HTTP ([0-9]{3}):",str(exc))
                            safe_status=int(matched.group(1)) if matched else None
                        except (TypeError,ValueError):
                            pass
                        self.record("model_call_retry",role=role,family=family,
                            provider=entry.provider,model=entry.model,
                            kind=exc.kind,http_status=safe_status,
                            attempt=2,delay_seconds=delay,
                            max_output_tokens=output_tokens,
                            formatting="none" if formatting is None else "structured")
                        await asyncio.sleep(delay)
                        remaining=budget.allowed(endpoint_timeout,
                                                 synthesis=synthesis)
                        if remaining<=5:
                            raise
                        # Every retry consumes a separately reserved request.
                        estimated_tokens=max(1,len(message)//3)+output_tokens
                        await self.quota.acquire(
                            entry.provider, entry.model,
                            deadline=time.monotonic()+remaining,
                            expected_tokens=estimated_tokens)
                        timeout=min(remaining,endpoint_timeout)
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
                if failures:
                    self.record("fallback_selected", role=role, family=family,
                                provider=entry.provider, model=entry.model,
                                skipped=list(failures))
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
                retry_after = exc.retry_after
                import re
                status_match = re.match(r"HTTP ([0-9]{3}):", str(exc))
                http_status = int(status_match.group(1)) if status_match else None
            except (KeyError, TypeError, ValueError):
                kind = "invalid_response"
            # No underlying exception content, URLs or keys are persisted.
            self.cache.failure(entry.provider, entry.model, kind,
                               retry_after=retry_after)
            self.quota.failure(entry.provider, entry.model, kind=kind,
                               retry_after=retry_after)
            failures.append(entry.provider + "/" + entry.model + ": " + kind)
            self.record("model_call_failed", role=role, family=family,
                        provider=entry.provider, model=entry.model, kind=kind,
                        http_status=http_status,
                        retry_after=retry_after)
            if budget.allowed(endpoint_timeout, synthesis=synthesis) <= 1:
                break
        raise FamilyUnavailable(family, failures)

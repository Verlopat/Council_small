"""Thin family-aware adapter over the tested Verlopat/test model_router.

The upstream API currently exposes normalized text, not raw provider response
JSON/headers. Calls are tracked honestly as text-only until raw transport exists.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
import hashlib
import os
import time
from pathlib import Path

from model_router import Candidate, KEY_NAMES, Router, redacted
from router_errors import CandidateError
from router_health import HealthCache
from council.budget import RunBudget
from council.families import endpoint_list

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

class FamilyTransport:
    def __init__(self, *, timeout: float = 28.0, health_file: Path | None = None,
                 record=None):
        self.timeout = timeout
        self.router = Router(timeout=timeout)
        self.cache = HealthCache(health_file or Path(".router_health.json"))
        self.record = record or (lambda *a, **k: None)

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
            try:
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
                self.record("model_call_started", role=role, family=family,
                            provider=entry.provider, model=entry.model,
                            prompt_hash=hashlib.sha256(message.encode()).hexdigest())
                text = await asyncio.wait_for(
                    asyncio.to_thread(self.router.generate, candidate, message,
                                      probe=False, request_timeout=max(0.5, timeout - 0.5)),
                    timeout=timeout)
                if not text.strip():
                    raise CandidateError("Empty response", kind="invalid_response")
                elapsed = time.monotonic() - t0
                self.cache.success(entry.provider, entry.model)
                self.record("model_call_succeeded", role=role, family=family,
                            provider=entry.provider, model=entry.model,
                            seconds=elapsed, response=text)
                return CallResult(family, entry.provider, entry.model, text, elapsed,
                                  hashlib.sha256(message.encode()).hexdigest())
            except (asyncio.TimeoutError, TimeoutError):
                kind = "timeout"
            except CandidateError as exc:
                kind = exc.kind
            except (KeyError, TypeError, ValueError):
                kind = "invalid_response"
            # No underlying exception content, URLs or keys are persisted.
            self.cache.failure(entry.provider, entry.model, kind)
            failures.append(entry.provider + "/" + entry.model + ": " + kind)
            self.record("model_call_failed", role=role, family=family,
                        provider=entry.provider, model=entry.model, kind=kind)
            if budget.allowed(self.timeout, synthesis=synthesis) <= 1:
                break
        raise FamilyUnavailable(family, failures)

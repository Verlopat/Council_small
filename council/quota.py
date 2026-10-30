"""FIFO request budget, provider cooldown and circuit breaker."""
from __future__ import annotations
import asyncio
import time

class TokenBucket:
    def __init__(self, rate_per_min: float, burst: int):
        if rate_per_min <= 0 or burst < 1:
            raise ValueError("Rate and burst must be positive")
        self.tokens = float(burst)
        self.capacity = float(burst)
        self.rate = rate_per_min / 60
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, deadline: float) -> bool:
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now-self.updated)*self.rate)
                self.updated = now
                if now >= deadline:
                    return False
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
                wait = (1-self.tokens)/self.rate
                if now + wait >= deadline:
                    return False
                await asyncio.sleep(wait)

    def observe_headers(self, headers: dict[str, str]) -> None:
        for key, value in headers.items():
            if key.lower() == "x-ratelimit-remaining-requests":
                try:
                    self.tokens = min(self.tokens, max(0, float(value)))
                except (TypeError, ValueError):
                    pass

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3):
        if failure_threshold < 1:
            raise ValueError("Invalid threshold")
        self.failures: dict[str,int] = {}
        self.until: dict[str,float] = {}
        self.threshold = failure_threshold

    def record_failure(self, endpoint: str, cooldown: float = 60.0) -> None:
        n = self.failures.get(endpoint, 0) + 1
        self.failures[endpoint] = n
        if n >= self.threshold:
            self.until[endpoint] = time.monotonic() + max(0, cooldown)

    def available(self, endpoint: str) -> bool:
        return (self.failures.get(endpoint, 0) < self.threshold or
                time.monotonic() >= self.until.get(endpoint, float("inf")))

    def record_probe_success(self, endpoint: str) -> None:
        self.failures.pop(endpoint, None)
        self.until.pop(endpoint, None)

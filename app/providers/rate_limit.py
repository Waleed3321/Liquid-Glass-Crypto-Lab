"""Token-bucket rate limiter shared by provider adapters."""

from __future__ import annotations

import asyncio
import time

from app.core.errors import RateLimitedError


class TokenBucket:
    """Refills linearly at ``per_minute / 60`` tokens per second.

    The bucket is sized below the provider's documented ceiling so a burst of
    scans can never trip an upstream ban.
    """

    def __init__(self, name: str, per_minute: int, capacity: int | None = None) -> None:
        self.name = name
        self.per_minute = max(1, per_minute)
        self.capacity = float(capacity or per_minute)
        self._tokens = self.capacity
        self._rate = self.per_minute / 60.0
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()
        self.denied = 0
        self.waited_seconds = 0.0

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self._rate)
            self._updated = now

    async def acquire(self, tokens: float = 1.0, wait_seconds: float = 3.0) -> bool:
        deadline = time.monotonic() + wait_seconds
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                missing = tokens - self._tokens
                wait = max(0.02, missing / self._rate)
            if time.monotonic() + wait > deadline:
                self.denied += 1
                raise RateLimitedError(
                    f"Rate limit budget for {self.name} exhausted",
                    details={"provider": self.name, "per_minute": self.per_minute},
                )
            self.waited_seconds += wait
            await asyncio.sleep(min(wait, 0.5))

    def snapshot(self) -> dict[str, float | str]:
        self._refill()
        return {
            "provider": self.name,
            "available": round(self._tokens, 2),
            "capacity": self.capacity,
            "per_minute": self.per_minute,
            "denied": self.denied,
        }

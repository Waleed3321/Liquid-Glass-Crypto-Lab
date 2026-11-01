"""Tiny async TTL cache used to respect provider rate limits."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class AsyncTTLCache:
    def __init__(self, max_entries: int = 4096) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries
        self.hits = 0
        self.misses = 0

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                self._store.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        async with self._lock:
            if len(self._store) >= self._max_entries:
                now = time.monotonic()
                self._store = {k: v for k, v in self._store.items() if v[0] > now}
                if len(self._store) >= self._max_entries:
                    self._store.pop(next(iter(self._store)), None)
            self._store[key] = (time.monotonic() + ttl_seconds, value)

    async def get_or_set(
        self, key: str, ttl_seconds: float, factory: Callable[[], Awaitable[T]]
    ) -> T:
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        if value is not None:
            await self.set(key, value, ttl_seconds)
        return value

    def invalidate(self, prefix: str = "") -> None:
        if not prefix:
            self._store.clear()
            return
        for key in [k for k in self._store if k.startswith(prefix)]:
            self._store.pop(key, None)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "entries": len(self._store)}

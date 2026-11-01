"""In-process pub/sub used by Server-Sent Events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from app.core.clock import utc_now


class EventHub:
    def __init__(self, *, queue_size: int = 128) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._queue_size = queue_size
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        payload = {
            "type": event_type,
            "ts": utc_now().isoformat(),
            "data": data or {},
        }
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Slow client: drop the oldest event rather than block producers.
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def heartbeat_payload(self) -> dict[str, Any]:
        return {"type": "heartbeat", "ts": utc_now().isoformat(), "data": {}}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None

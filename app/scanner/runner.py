"""Owns the background scanner task, the tick guard and the database lease."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from app.core.clock import utc_now
from app.core.config import settings
from app.core.errors import REASON_SCANNER_BUSY
from app.core.logging import get_logger
from app.db.session import session_scope
from app.notifications.dispatcher import NotificationDispatcher
from app.providers.registry import Providers
from app.repositories.system import SystemRepository
from app.scanner.heartbeat import database_status
from app.scanner.lease import OWNER
from app.scanner.loop import run_loop
from app.scanner.tick import ScannerEngine, TickResult
from app.services.events import EventHub
from app.services.settings_service import load_scanner_config

logger = get_logger(__name__)


class ScannerRunner:
    def __init__(
        self,
        providers: Providers,
        hub: EventHub,
        dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self.providers = providers
        self.hub = hub
        self.dispatcher = dispatcher
        self.engine = ScannerEngine(providers, hub, dispatcher)
        self.owner = OWNER
        self._task: asyncio.Task | None = None
        self._tick_lock = asyncio.Lock()
        self.stopping_event = asyncio.Event()
        self.last_tick_at = None
        self.last_success_at = None
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.consecutive_failures = 0
        self.interval_seconds = settings.scan_interval_seconds
        self.enabled = settings.scanner_enabled

    # ------------------------------------------------------------------
    @property
    def stopping(self) -> bool:
        return self.stopping_event.is_set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def startup(self) -> None:
        async with session_scope() as session:
            repo = SystemRepository(session)
            recovered = await repo.mark_orphaned_runs()
        if recovered:
            logger.warning("scanner_orphaned_runs_recovered", extra={"count": recovered})
        async with session_scope() as session:
            scan_cfg = await load_scanner_config(session)
        self.interval_seconds = int(scan_cfg.get("interval_seconds", settings.scan_interval_seconds))
        self.enabled = bool(scan_cfg.get("enabled", settings.scanner_enabled))

    async def start(self) -> None:
        if self.running:
            return
        self.stopping_event = asyncio.Event()
        self._task = asyncio.create_task(run_loop(self), name="scanner-loop")
        logger.info("scanner_started")

    async def stop(self) -> None:
        self.stopping_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=20)
            except TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):  # noqa: B014
                    pass
            self._task = None
        async with session_scope() as session:
            await SystemRepository(session).release_lease(self.owner)
        logger.info("scanner_stopped")

    # ------------------------------------------------------------------
    def _skipped(self, reason: str) -> TickResult:
        result = TickResult(status="SKIPPED", skipped_reason=reason, error_summary=None)
        self.last_result = result.as_dict()
        return result

    async def tick(self, source: str = "manual") -> TickResult:
        if self._tick_lock.locked():
            return self._skipped(REASON_SCANNER_BUSY)

        async with self._tick_lock:
            interval = self.interval_seconds
            async with session_scope() as session:
                repo = SystemRepository(session)
                acquired = await repo.acquire_lease(
                    self.owner, settings.lease_ttl_seconds, interval
                )
                if not acquired:
                    return self._skipped("Another scanner instance holds the lease.")
                scan_cfg = await load_scanner_config(session)
                interval = int(scan_cfg.get("interval_seconds", settings.scan_interval_seconds))
                self.interval_seconds = interval
                self.enabled = bool(scan_cfg.get("enabled", settings.scanner_enabled))
                lease = await repo.get_lease()
                last_tick = lease.last_tick_at if lease else None
                if scan_cfg.get("enabled", True) and source != "manual":
                    gap = settings.min_tick_gap_seconds
                    if last_tick is not None and (utc_now() - last_tick) < timedelta(seconds=gap):
                        return self._skipped(f"Minimum tick gap of {gap}s not elapsed.")

            result = await self.engine.tick(source)

            async with session_scope() as session:
                await SystemRepository(session).heartbeat(
                    self.owner,
                    settings.lease_ttl_seconds,
                    tick_done=result.status != "SKIPPED",
                )

            now = utc_now()
            self.last_tick_at = now
            self.last_result = result.as_dict()
            if result.status == "FAILED":
                self.consecutive_failures += 1
                self.last_error = result.error_summary
            elif result.status in {"COMPLETED", "DEGRADED"}:
                self.last_success_at = now
                self.consecutive_failures = 0
                self.last_error = result.error_summary
            return result

    # ------------------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        db = await database_status()
        now = utc_now()
        next_scan = (
            (self.last_tick_at + timedelta(seconds=self.interval_seconds)).isoformat()
            if self.last_tick_at
            else (now + timedelta(seconds=self.interval_seconds)).isoformat()
        )
        stale = False
        if self.last_success_at:
            stale = (now - self.last_success_at).total_seconds() > self.interval_seconds * 3
        else:
            stale = True
        return {
            "state": "running" if self.running else "stopped",
            "enabled": self.enabled,
            "owner": self.owner,
            "interval_seconds": self.interval_seconds,
            "min_tick_gap_seconds": settings.min_tick_gap_seconds,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_success_at": self.last_success_at.isoformat()
            if self.last_success_at
            else db.get("last_success_at"),
            "next_scan_at": next_scan,
            "stale": stale,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "last_result": self.last_result,
            "subscribers": self.hub.subscriber_count,
            "providers": self.providers.health(),
            **db,
        }

    async def next_interval(self) -> int:
        async with session_scope() as session:
            scan_cfg = await load_scanner_config(session)
        self.interval_seconds = int(scan_cfg.get("interval_seconds", settings.scan_interval_seconds))
        return self.interval_seconds

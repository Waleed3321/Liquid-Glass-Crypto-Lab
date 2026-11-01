"""Persistence helpers for scanner runs, notifications, decisions and settings."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.models import (
    AppSetting,
    MarketSnapshot,
    Notification,
    ScannerLease,
    ScannerRun,
    StrategyDecision,
)
from app.models.enums import NotificationStatus, ScannerRunStatus


class SystemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- scanner runs ------------------------------------------------------
    async def start_run(self, source: str = "loop") -> ScannerRun:
        run = ScannerRun(started_at=utc_now(), status=ScannerRunStatus.RUNNING.value, source=source)
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish_run(self, run: ScannerRun, *, status: str, **counters: int) -> ScannerRun:
        run.status = status
        run.finished_at = utc_now()
        duration = (run.finished_at - run.started_at).total_seconds()
        run.duration_ms = int(duration * 1000)
        for key, value in counters.items():
            if hasattr(run, key):
                setattr(run, key, value)
        await self.session.flush()
        return run

    async def latest_run(self) -> ScannerRun | None:
        return (
            await self.session.execute(
                select(ScannerRun).order_by(ScannerRun.started_at.desc()).limit(1)
            )
        ).scalar_one_or_none()

    async def last_completed_run(self) -> ScannerRun | None:
        return (
            await self.session.execute(
                select(ScannerRun)
                .where(
                    ScannerRun.status.in_(
                        [
                            ScannerRunStatus.COMPLETED.value,
                            ScannerRunStatus.DEGRADED.value,
                        ]
                    )
                )
                .order_by(ScannerRun.finished_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def recent_runs(self, limit: int = 20) -> list[ScannerRun]:
        return list(
            (
                await self.session.execute(
                    select(ScannerRun).order_by(ScannerRun.started_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def mark_orphaned_runs(self) -> int:
        result = await self.session.execute(
            update(ScannerRun)
            .where(ScannerRun.status == ScannerRunStatus.RUNNING.value)
            .values(status=ScannerRunStatus.INTERRUPTED.value, finished_at=utc_now())
        )
        return int(result.rowcount or 0)

    async def scanner_error_count(self, since: datetime) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count(ScannerRun.id)).where(
                        ScannerRun.started_at >= since,
                        ScannerRun.status.in_(
                            [ScannerRunStatus.FAILED.value, ScannerRunStatus.DEGRADED.value]
                        ),
                    )
                )
            ).scalar_one()
        )

    # -- lease -------------------------------------------------------------
    async def get_lease(self, *, for_update: bool = False) -> ScannerLease | None:
        query = select(ScannerLease).where(ScannerLease.id == 1)
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def acquire_lease(self, owner: str, ttl_seconds: int, interval: int) -> bool:
        now = utc_now()
        lease = await self.get_lease()
        if lease is None:
            lease = ScannerLease(
                id=1,
                owner=owner,
                heartbeat_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                last_tick_at=None,
                interval_seconds=interval,
            )
            self.session.add(lease)
            await self.session.flush()
            return True
        if lease.owner != owner and lease.expires_at > now:
            return False
        lease.owner = owner
        lease.heartbeat_at = now
        lease.expires_at = now + timedelta(seconds=ttl_seconds)
        lease.interval_seconds = interval
        await self.session.flush()
        return True

    async def heartbeat(self, owner: str, ttl_seconds: int, *, tick_done: bool = False) -> None:
        lease = await self.get_lease()
        if lease is None or lease.owner != owner:
            return
        now = utc_now()
        lease.heartbeat_at = now
        lease.expires_at = now + timedelta(seconds=ttl_seconds)
        if tick_done:
            lease.last_tick_at = now
        await self.session.flush()

    async def release_lease(self, owner: str) -> None:
        lease = await self.get_lease()
        if lease is not None and lease.owner == owner:
            lease.expires_at = utc_now()
            await self.session.flush()

    # -- decisions ---------------------------------------------------------
    async def add_decision(
        self,
        *,
        token_id: int | None,
        action: str,
        reason_codes: list[str],
        metrics: dict[str, Any] | None = None,
        pair_id: int | None = None,
        position_id: int | None = None,
        strategy: str = "A",
        note: str | None = None,
    ) -> StrategyDecision:
        row = StrategyDecision(
            token_id=token_id,
            pair_id=pair_id,
            position_id=position_id,
            strategy=strategy,
            action=action,
            reason_codes=reason_codes,
            metrics=metrics or {},
            note=note,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent_decisions(self, limit: int = 50) -> list[StrategyDecision]:
        return list(
            (
                await self.session.execute(
                    select(StrategyDecision)
                    .order_by(StrategyDecision.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    # -- notifications -----------------------------------------------------
    async def add_notification(
        self,
        *,
        kind: str,
        title: str,
        message: str,
        severity: str = "INFO",
        payload: dict[str, Any] | None = None,
    ) -> Notification:
        row = Notification(
            kind=kind,
            title=title,
            message=message,
            severity=severity,
            payload=payload or {},
            status=NotificationStatus.PENDING.value,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent_notifications(self, limit: int = 50) -> list[Notification]:
        return list(
            (
                await self.session.execute(
                    select(Notification).order_by(Notification.created_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def pending_notifications(self, limit: int = 20, max_attempts: int = 5) -> list[Notification]:
        return list(
            (
                await self.session.execute(
                    select(Notification)
                    .where(
                        Notification.status == NotificationStatus.PENDING.value,
                        Notification.attempts < max_attempts,
                    )
                    .order_by(Notification.created_at.asc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    # -- settings ----------------------------------------------------------
    async def get_setting(self, key: str) -> Any:
        row = await self.session.get(AppSetting, key)
        return row.value if row else None

    async def set_setting(self, key: str, value: Any) -> AppSetting:
        row = await self.session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value)
            self.session.add(row)
        else:
            row.value = value
            row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def all_settings(self) -> dict[str, Any]:
        rows = (await self.session.execute(select(AppSetting))).scalars().all()
        return {row.key: row.value for row in rows}

    # -- retention ---------------------------------------------------------
    async def snapshot_stats(self) -> tuple[int, int]:
        total = int(
            (await self.session.execute(select(func.count(MarketSnapshot.id)))).scalar_one()
        )
        oldest = (
            await self.session.execute(select(func.min(MarketSnapshot.ts)))
        ).scalar_one()
        return total, int(oldest.timestamp()) if oldest else 0

    async def delete_snapshots_before(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            delete(MarketSnapshot).where(MarketSnapshot.ts < cutoff)
        )
        return int(result.rowcount or 0)

"""Scanner status snapshot merged from memory and the database."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.clock import utc_now
from app.db.session import session_scope
from app.models.enums import ScannerRunStatus
from app.repositories.system import SystemRepository


async def database_status() -> dict[str, Any]:
    async with session_scope() as session:
        repo = SystemRepository(session)
        latest = await repo.latest_run()
        last_completed = await repo.last_completed_run()
        recent = await repo.recent_runs(limit=12)
        lease = await repo.get_lease()
        errors = await repo.scanner_error_count(utc_now() - timedelta(hours=1))
        return {
            "last_run": _run_dict(latest),
            "last_success_at": last_completed.finished_at.isoformat()
            if last_completed and last_completed.finished_at
            else None,
            "recent_runs": [_run_dict(run) for run in recent],
            "errors_last_hour": errors,
            "lease": {
                "owner": lease.owner if lease else None,
                "heartbeat_at": lease.heartbeat_at.isoformat() if lease else None,
                "expires_at": lease.expires_at.isoformat() if lease else None,
                "last_tick_at": lease.last_tick_at.isoformat()
                if lease and lease.last_tick_at
                else None,
                "interval_seconds": lease.interval_seconds if lease else None,
            },
        }


def _run_dict(run) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "source": run.source,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "discovered": run.discovered,
        "enriched": run.enriched,
        "snapshots": run.snapshots,
        "scored": run.scored,
        "entries": run.entries,
        "exits": run.exits,
        "skipped": run.skipped,
        "errors": run.errors,
        "error_summary": run.error_summary,
        "running": run.status == ScannerRunStatus.RUNNING.value,
    }

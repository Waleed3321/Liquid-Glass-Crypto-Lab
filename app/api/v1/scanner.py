"""Scanner control and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_scanner, get_session_dep
from app.core.errors import UnauthorizedError
from app.core.security import constant_time_equals, require_admin
from app.repositories.system import SystemRepository
from app.scanner.runner import ScannerRunner

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.get("/status")
async def scanner_status(scanner: ScannerRunner = Depends(get_scanner)) -> dict:
    return await scanner.status()


@router.get("/runs")
async def scanner_runs(
    limit: int = 20, session: AsyncSession = Depends(get_session_dep)
) -> dict:
    runs = await SystemRepository(session).recent_runs(limit=max(1, min(limit, 100)))
    return {
        "runs": [
            {
                "id": run.id,
                "status": run.status,
                "source": run.source,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "duration_ms": run.duration_ms,
                "discovered": run.discovered,
                "snapshots": run.snapshots,
                "scored": run.scored,
                "entries": run.entries,
                "exits": run.exits,
                "errors": run.errors,
                "error_summary": run.error_summary,
            }
            for run in runs
        ]
    }


@router.post("/start", dependencies=[Depends(require_admin)])
async def scanner_start(scanner: ScannerRunner = Depends(get_scanner)) -> dict:
    await scanner.start()
    return {"state": "running" if scanner.running else "stopped", "status": await scanner.status()}


@router.post("/stop", dependencies=[Depends(require_admin)])
async def scanner_stop(scanner: ScannerRunner = Depends(get_scanner)) -> dict:
    await scanner.stop()
    return {"state": "stopped", "status": await scanner.status()}


@router.post("/tick")
async def scanner_tick(
    scanner: ScannerRunner = Depends(get_scanner),
    x_scan_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Run one scan now. Used by the external cron keep-alive.

    When ``SCANNER_TICK_TOKEN`` is configured the header must match. Otherwise
    the optional admin token applies.
    """
    expected = settings.scanner_tick_token
    if expected:
        if not x_scan_token or not constant_time_equals(x_scan_token, expected):
            raise UnauthorizedError("Invalid scanner tick token.")
    elif settings.admin_token:
        if not x_admin_token or not constant_time_equals(x_admin_token, settings.admin_token):
            raise UnauthorizedError("Admin token required for manual ticks.")

    result = await scanner.tick(source="cron")
    return result.as_dict()

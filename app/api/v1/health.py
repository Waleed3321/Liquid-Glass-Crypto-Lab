"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.clock import utc_now
from app.core.config import settings
from app.core.deps import get_scanner
from app.db.session import ping_database
from app.scanner.runner import ScannerRunner

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, scanner: ScannerRunner = Depends(get_scanner)) -> dict:
    database_ok = await ping_database()
    status = await scanner.status()
    return {
        "status": "ok" if database_ok else "degraded",
        "app": settings.app_name,
        "version": settings.version,
        "environment": settings.app_env,
        "time": utc_now().isoformat(),
        "database": "ok" if database_ok else "unavailable",
        "paper_only": True,
        "scanner": {
            "state": status.get("state"),
            "enabled": status.get("enabled"),
            "last_success_at": status.get("last_success_at"),
            "next_scan_at": status.get("next_scan_at"),
            "interval_seconds": status.get("interval_seconds"),
            "stale": status.get("stale"),
        },
        "discord": {
            "configured": request.app.state.dispatcher.configured,
        },
        "limits": {
            "initial_balance_usd": settings.initial_balance_usd,
            "max_open_positions": settings.max_open_positions,
            "max_position_usd": settings.max_position_usd,
            "daily_loss_limit_usd": settings.daily_loss_limit_usd,
            "max_price_impact_pct": settings.max_price_impact_pct,
        },
    }


@router.get("/health/ready")
async def ready(scanner: ScannerRunner = Depends(get_scanner)):
    database_ok = await ping_database()
    status = await scanner.status()
    ready_ok = database_ok
    body = {
        "ready": ready_ok,
        "database": "ok" if database_ok else "unavailable",
        "scanner": status.get("state"),
        "scanner_stale": status.get("stale"),
    }
    return JSONResponse(status_code=200 if ready_ok else 503, content=body)

"""Notification log, Discord test and outbox dispatching."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_dispatcher, get_session_dep
from app.core.security import require_admin
from app.models import Notification
from app.notifications.dispatcher import NotificationDispatcher
from app.repositories.system import SystemRepository
from app.services.settings_service import load_notification_config

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _row(row: Notification) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "severity": row.severity,
        "title": row.title,
        "message": row.message,
        "payload": row.payload or {},
        "status": row.status,
        "attempts": row.attempts,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
    }


@router.get("")
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session_dep),
    dispatcher: NotificationDispatcher = Depends(get_dispatcher),
) -> dict:
    rows = await SystemRepository(session).recent_notifications(limit=limit)
    statuses = Counter(row.status for row in rows)
    config = await load_notification_config(session)
    return {
        "notifications": [_row(row) for row in rows],
        "count": len(rows),
        "status_counts": dict(statuses),
        "config": config,
        "transport": {
            "configured": dispatcher.configured,
            "mode": dispatcher.notifier.mode if dispatcher.notifier else "disabled",
        },
    }


@router.post("/test", dependencies=[Depends(require_admin)])
async def send_test(dispatcher: NotificationDispatcher = Depends(get_dispatcher)) -> dict:
    return await dispatcher.send_test()


@router.post("/dispatch", dependencies=[Depends(require_admin)])
async def dispatch(dispatcher: NotificationDispatcher = Depends(get_dispatcher)) -> dict:
    return {"sent": await dispatcher.dispatch_pending()}

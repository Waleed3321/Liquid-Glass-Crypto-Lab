"""Outbox dispatcher: sends queued notifications to Discord without blocking trades.

Discord outages are isolated: a failed send keeps the row pending for retry and
never raises into the trading or scanner path.
"""

from __future__ import annotations

from app.core.clock import utc_now
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models import Notification
from app.models.enums import NotificationKind, NotificationStatus, Severity
from app.notifications.templates import to_message
from app.providers.discord import DiscordNotifier
from app.repositories.system import SystemRepository
from app.services.events import EventHub

logger = get_logger(__name__)


class NotificationDispatcher:
    def __init__(self, notifier: DiscordNotifier | None, hub: EventHub | None = None) -> None:
        self.notifier = notifier
        self.hub = hub

    @property
    def configured(self) -> bool:
        return bool(self.notifier and self.notifier.configured and self.notifier.enabled)

    async def queue(
        self,
        *,
        kind: str,
        title: str,
        message: str,
        severity: str = Severity.INFO.value,
        payload: dict | None = None,
    ) -> int:
        async with session_scope() as session:
            row = await SystemRepository(session).add_notification(
                kind=kind, title=title, message=message, severity=severity, payload=payload or {}
            )
            await session.flush()
            return row.id

    async def dispatch_pending(self) -> int:
        if not self.configured:
            await self._mark_unconfigured()
            return 0

        sent = 0
        async with session_scope() as session:
            repo = SystemRepository(session)
            pending = await repo.pending_notifications(
                limit=20, max_attempts=settings.notification_max_attempts
            )
            if not pending:
                return 0

            for row in pending:
                ok = await self.notifier.send(to_message(row))
                row.attempts += 1
                if ok:
                    row.status = NotificationStatus.SENT.value
                    row.sent_at = utc_now()
                    sent += 1
                else:
                    row.last_error = (self.notifier.last_error or "unknown error")[:500]
                    if row.attempts >= settings.notification_max_attempts:
                        row.status = NotificationStatus.FAILED.value
                        logger.warning(
                            "notification_failed_permanently",
                            extra={"notification_id": row.id, "error": row.last_error},
                        )
            await session.flush()

        if sent and self.hub:
            await self.hub.publish("notifications", {"sent": sent})
        return sent

    async def send_test(self) -> dict[str, object]:
        if not self.notifier or not self.notifier.configured:
            return {
                "delivered": False,
                "configured": False,
                "detail": "Set DISCORD_WEBHOOK_URL (or bot token + channel id) to enable Discord delivery.",
            }
        notification = Notification(
            kind=NotificationKind.TEST.value,
            title="Liquid Glass Crypto Lab test",
            message="Discord delivery is configured correctly. Paper trading only — no real funds are ever used.",
            severity=Severity.INFO.value,
            payload={"chain": "solana"},
        )
        delivered = await self.notifier.send(to_message(notification))
        await self.queue(
            kind=NotificationKind.TEST.value,
            title=notification.title,
            message=notification.message,
            severity=notification.severity,
            payload=notification.payload,
        )
        return {
            "delivered": delivered,
            "configured": True,
            "mode": self.notifier.mode,
            "error": self.notifier.last_error,
        }

    async def _mark_unconfigured(self) -> None:
        async with session_scope() as session:
            repo = SystemRepository(session)
            pending = await repo.pending_notifications(limit=50)
            for row in pending:
                row.status = NotificationStatus.SKIPPED.value
                row.last_error = "Discord is not configured"
            await session.flush()

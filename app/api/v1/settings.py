"""Application settings endpoints.

Secrets are never returned: only booleans describing whether a transport is
configured, plus the masked identifiers safe to display.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_dispatcher, get_providers, get_scanner, get_session_dep
from app.core.errors import ValidationError
from app.core.security import require_admin
from app.notifications.dispatcher import NotificationDispatcher
from app.providers.registry import Providers
from app.scanner.runner import ScannerRunner
from app.schemas.settings import SettingsIn
from app.services.settings_service import (
    load_notification_config,
    load_scanner_config,
    load_strategy_config,
    save_notification_config,
    save_scanner_config,
    save_strategy_config,
)

router = APIRouter(prefix="/settings", tags=["settings"])


async def _payload(
    session: AsyncSession,
    scanner: ScannerRunner,
    dispatcher: NotificationDispatcher,
    providers: Providers,
) -> dict:
    strategy = await load_strategy_config(session)
    return {
        "strategy": strategy.public_dict(),
        "scanner": await load_scanner_config(session),
        "notifications": await load_notification_config(session),
        "scanner_runtime": {
            "enabled": scanner.enabled,
            "running": scanner.running,
            "interval_seconds": scanner.interval_seconds,
        },
        "limits": {
            "initial_balance_usd": 10.0,
            "max_open_positions": 3,
            "max_position_usd": 2.5,
            "daily_loss_limit_usd": 0.5,
            "max_price_impact_pct": 1.0,
        },
        "integrations": {
            "discord": {
                "configured": dispatcher.configured,
                "mode": dispatcher.notifier.mode if dispatcher.notifier else "disabled",
                "webhook_set": bool(settings.discord_webhook_url),
                "bot_set": bool(settings.discord_bot_token and settings.discord_channel_id),
                "channel_id": settings.discord_channel_id or None,
                "webhook_fingerprint": (
                    settings.discord_webhook_url[-6:] if settings.discord_webhook_url else None
                ),
            },
            "scanner_tick_token_set": bool(settings.scanner_tick_token),
            "admin_token_set": bool(settings.admin_token),
            "providers": providers.health(),
        },
        "environment": {
            "app_env": settings.app_env,
            "version": settings.version,
            "database_backend": "postgresql" if not settings.is_sqlite else "sqlite",
            "paper_only": True,
            "discovery_window_hours": settings.discovery_window_hours,
            "scan_interval_seconds": settings.scan_interval_seconds,
            "retention_days": settings.snapshot_full_days,
        },
    }


@router.get("")
async def read_settings(
    session: AsyncSession = Depends(get_session_dep),
    scanner: ScannerRunner = Depends(get_scanner),
    dispatcher: NotificationDispatcher = Depends(get_dispatcher),
    providers: Providers = Depends(get_providers),
) -> dict:
    return await _payload(session, scanner, dispatcher, providers)


@router.put("", dependencies=[Depends(require_admin)])
async def update_settings(
    payload: SettingsIn,
    session: AsyncSession = Depends(get_session_dep),
    scanner: ScannerRunner = Depends(get_scanner),
    dispatcher: NotificationDispatcher = Depends(get_dispatcher),
    providers: Providers = Depends(get_providers),
) -> dict:
    if payload.strategy is not None:
        await save_strategy_config(session, payload.strategy.overrides())
    if payload.scanner is not None:
        values = payload.scanner.overrides()
        if values:
            await save_scanner_config(session, values)
        if "interval_seconds" in values:
            scanner.interval_seconds = int(values["interval_seconds"])
        if "enabled" in values:
            scanner.enabled = bool(values["enabled"])
            if scanner.enabled and not scanner.running:
                await scanner.start()
            elif not scanner.enabled and scanner.running:
                await scanner.stop()
    if payload.notifications is not None:
        await save_notification_config(session, payload.notifications.overrides())
    if payload.strategy is None and payload.scanner is None and payload.notifications is None:
        raise ValidationError("No settings supplied.")
    await session.commit()
    return await _payload(session, scanner, dispatcher, providers)

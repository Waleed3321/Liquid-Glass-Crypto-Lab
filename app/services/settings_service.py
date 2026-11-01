"""Runtime settings persisted in ``app_settings`` (strategy thresholds, scanner)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.system import SystemRepository
from app.strategies.config import StrategyConfig

STRATEGY_KEY = "strategy.config"
SCANNER_KEY = "scanner.config"
NOTIFICATION_KEY = "notifications.config"

_HARD_FIELD_DEFAULTS = {
    "max_open_positions": 3,
    "max_position_usd": 2.5,
    "daily_loss_limit_usd": 0.5,
    "max_price_impact_pct": 1.0,
}


async def load_strategy_config(session: AsyncSession) -> StrategyConfig:
    overrides = await SystemRepository(session).get_setting(STRATEGY_KEY)
    try:
        return StrategyConfig().merged(overrides or {})
    except Exception:
        return StrategyConfig()


async def save_strategy_config(session: AsyncSession, overrides: dict[str, Any]) -> StrategyConfig:
    repo = SystemRepository(session)
    current = await repo.get_setting(STRATEGY_KEY) or {}
    merged = {**current, **{k: v for k, v in overrides.items() if v is not None}}
    config = StrategyConfig().merged(merged)
    await repo.set_setting(STRATEGY_KEY, config.model_dump())
    return config


async def load_scanner_config(session: AsyncSession) -> dict[str, Any]:
    stored = await SystemRepository(session).get_setting(SCANNER_KEY) or {}
    return {
        "enabled": bool(stored.get("enabled", settings.scanner_enabled)),
        "interval_seconds": int(
            stored.get("interval_seconds", settings.scan_interval_seconds)
        ),
        "min_observation_minutes": float(
            stored.get("min_observation_minutes", StrategyConfig().min_observation_minutes)
        ),
        "discovery_window_hours": float(
            stored.get("discovery_window_hours", settings.discovery_window_hours)
        ),
    }


async def save_scanner_config(session: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    repo = SystemRepository(session)
    current = await repo.get_setting(SCANNER_KEY) or {}
    merged = {**current, **{k: v for k, v in values.items() if v is not None}}
    if "interval_seconds" in merged:
        merged["interval_seconds"] = max(30, min(300, int(merged["interval_seconds"])))
    if "discovery_window_hours" in merged:
        merged["discovery_window_hours"] = max(1.0, min(24.0, float(merged["discovery_window_hours"])))
    await repo.set_setting(SCANNER_KEY, merged)
    return await load_scanner_config(session)


async def load_notification_config(session: AsyncSession) -> dict[str, Any]:
    stored = await SystemRepository(session).get_setting(NOTIFICATION_KEY) or {}
    return {
        "enabled": bool(stored.get("enabled", settings.discord_enabled)),
        "min_score_for_alert": float(stored.get("min_score_for_alert", 70.0)),
        "notify_security_warnings": bool(stored.get("notify_security_warnings", False)),
        "notify_entries": bool(stored.get("notify_entries", True)),
        "notify_exits": bool(stored.get("notify_exits", True)),
    }


async def save_notification_config(session: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    repo = SystemRepository(session)
    current = await repo.get_setting(NOTIFICATION_KEY) or {}
    merged = {**current, **{k: v for k, v in values.items() if v is not None}}
    if "min_score_for_alert" in merged:
        merged["min_score_for_alert"] = max(0.0, min(100.0, float(merged["min_score_for_alert"])))
    await repo.set_setting(NOTIFICATION_KEY, merged)
    return await load_notification_config(session)

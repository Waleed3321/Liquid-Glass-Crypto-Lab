"""Time helpers.

All timestamps are stored timezone-aware in UTC. The trading day boundary is
configurable so a daily loss limit cannot be reset by restarting the process.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.core.config import settings


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def trading_day(moment: datetime | None = None) -> date:
    """Return the accounting day for ``moment``.

    A rollover hour of 0 means UTC midnight; other values shift the boundary
    (for example 8 means the day rolls over at 08:00 UTC).
    """
    moment = ensure_utc(moment) or utc_now()
    shifted = moment - timedelta(hours=settings.trading_day_rollover_hour)
    return shifted.date()


def iso(value: datetime | None) -> str | None:
    value = ensure_utc(value)
    return value.isoformat() if value else None


def seconds_since(value: datetime | None, now: datetime | None = None) -> float | None:
    value = ensure_utc(value)
    if value is None:
        return None
    now = ensure_utc(now) or utc_now()
    return (now - value).total_seconds()


def from_iso_timestamp(value: str | int | float | None) -> datetime | None:
    """Parse ISO strings or epoch milliseconds (DEX Screener uses ms)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ensure_utc(parsed)

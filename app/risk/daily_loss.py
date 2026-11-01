"""Trading-day helpers used by the daily-loss guard and reporting."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.core.clock import trading_day, utc_now
from app.models import DailyPerformance


def current_trading_day(now: datetime | None = None) -> date:
    return trading_day(utc_now() if now is None else now)


def realized_today(daily: DailyPerformance | None) -> Decimal:
    if daily is None:
        return Decimal("0")
    return daily.realized_pnl or Decimal("0")


def loss_limit_reached(daily: DailyPerformance | None, limit_usd: float) -> bool:
    if daily is None:
        return False
    if daily.halted:
        return True
    return float(realized_today(daily)) <= -abs(limit_usd)


def remaining_budget(daily: DailyPerformance | None, limit_usd: float) -> Decimal:
    spent = realized_today(daily)
    return Decimal(str(limit_usd)) + spent

"""Portfolio valuation, unrealised P&L and performance aggregates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.models import Position
from app.repositories.tokens import TokenRepository
from app.repositories.trading import TradingRepository
from app.risk.daily_loss import current_trading_day
from app.risk.limits import RiskLimits


def _f(value: Decimal | float | int | None) -> float:
    return float(value or 0)


@dataclass(slots=True)
class PositionView:
    id: int
    token_id: int
    symbol: str
    name: str
    chain: str
    address: str
    status: str
    qty: float
    remaining_qty: float
    entry_price: float
    entry_notional: float
    invested_usd: float
    entry_fees: float
    realized_pnl: float
    fees_paid: float
    market_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pct: float
    peak_price: float
    trail_high: float
    protection_armed: bool
    opened_at: str | None
    closed_at: str | None
    exit_reason: str | None
    price_age_seconds: float | None
    security_status: str | None = None
    as_of: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "token_id": self.token_id,
            "symbol": self.symbol,
            "name": self.name,
            "chain": self.chain,
            "address": self.address,
            "status": self.status,
            "qty": self.qty,
            "remaining_qty": self.remaining_qty,
            "entry_price": self.entry_price,
            "entry_notional": self.entry_notional,
            "invested_usd": self.invested_usd,
            "entry_fees": self.entry_fees,
            "realized_pnl": self.realized_pnl,
            "fees_paid": self.fees_paid,
            "market_price": self.market_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pct": self.unrealized_pct,
            "peak_price": self.peak_price,
            "trail_high": self.trail_high,
            "protection_armed": self.protection_armed,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "exit_reason": self.exit_reason,
            "price_age_seconds": self.price_age_seconds,
            "security_status": self.security_status,
            "as_of": self.as_of,
            "estimated": True,
        }


@dataclass(slots=True)
class PortfolioSummary:
    account_id: int
    initial_balance: float
    cash_balance: float
    invested_usd: float
    market_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_pnl_pct: float
    daily_realized_pnl: float
    daily_pnl: float
    open_positions: int
    max_open_positions: int
    daily_loss_limit: float
    daily_loss_used: float
    daily_loss_remaining: float
    halted: bool
    win_rate: float
    closed_positions: int
    wins: int
    losses: int
    positions: list[PositionView] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "initial_balance": self.initial_balance,
            "cash_balance": self.cash_balance,
            "invested_usd": self.invested_usd,
            "market_value": self.market_value,
            "equity": self.equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "daily_realized_pnl": self.daily_realized_pnl,
            "daily_pnl": self.daily_pnl,
            "open_positions": self.open_positions,
            "max_open_positions": self.max_open_positions,
            "daily_loss_limit": self.daily_loss_limit,
            "daily_loss_used": self.daily_loss_used,
            "daily_loss_remaining": self.daily_loss_remaining,
            "halted": self.halted,
            "win_rate": self.win_rate,
            "closed_positions": self.closed_positions,
            "wins": self.wins,
            "losses": self.losses,
            "positions": [p.as_dict() for p in self.positions],
            "estimated": True,
        }


async def _position_views(session: AsyncSession, positions: list[Position]) -> list[PositionView]:
    tokens = TokenRepository(session)
    checks = await tokens.latest_security([p.token_id for p in positions])
    views: list[PositionView] = []
    now = utc_now()
    for position in positions:
        token = await tokens.get(position.token_id)
        pair = await tokens.primary_pair(position.token_id)
        snapshot = await tokens.latest_snapshot(pair.id) if pair else None
        price = _f(snapshot.price_usd) if snapshot else _f(position.entry_price)
        remaining = _f(position.remaining_qty)
        invested = _f(position.invested_usd)
        market_value = remaining * price
        unrealized = market_value - invested
        unrealized_pct = (unrealized / invested * 100.0) if invested > 0 else 0.0
        age = (now - snapshot.ts).total_seconds() if snapshot else None
        check = checks.get(position.token_id)
        views.append(
            PositionView(
                id=position.id,
                token_id=position.token_id,
                symbol=token.symbol if token else "",
                name=token.name if token else "",
                chain=token.chain if token else "",
                address=token.address if token else "",
                status=position.status,
                qty=_f(position.qty),
                remaining_qty=remaining,
                entry_price=_f(position.entry_price),
                entry_notional=_f(position.entry_notional),
                invested_usd=invested,
                entry_fees=_f(position.entry_fees),
                realized_pnl=_f(position.realized_pnl),
                fees_paid=_f(position.fees_paid),
                market_price=price,
                market_value=market_value,
                unrealized_pnl=unrealized,
                unrealized_pct=unrealized_pct,
                peak_price=_f(position.peak_price),
                trail_high=_f(position.trail_high),
                protection_armed=position.protection_armed,
                opened_at=position.opened_at.isoformat() if position.opened_at else None,
                closed_at=position.closed_at.isoformat() if position.closed_at else None,
                exit_reason=position.exit_reason,
                price_age_seconds=round(age, 1) if age is not None else None,
                security_status=check.overall if check else None,
                as_of=snapshot.ts.isoformat() if snapshot else None,
            )
        )
    return views


async def build_summary(session: AsyncSession, limits: RiskLimits | None = None) -> PortfolioSummary:
    limits = limits or RiskLimits.from_config()
    trading = TradingRepository(session)
    account = await trading.account()
    if account is None:
        raise RuntimeError("Paper account missing")
    positions = await trading.open_positions(account.id)
    views = await _position_views(session, positions)
    closed = await trading.closed_positions(account.id)
    day = current_trading_day()
    daily = await trading.daily(account.id, day)

    invested = sum(v.invested_usd for v in views)
    market_value = sum(v.market_value for v in views)
    unrealized = market_value - invested
    cash = _f(account.cash_balance)
    equity = cash + market_value
    initial = _f(account.initial_balance)
    realized = _f(account.realized_pnl)
    total_pnl = equity - initial
    wins = sum(1 for p in closed if _f(p.realized_pnl) > 0)
    losses = sum(1 for p in closed if _f(p.realized_pnl) < 0)
    daily_realized = _f(daily.realized_pnl) if daily else 0.0

    return PortfolioSummary(
        account_id=account.id,
        initial_balance=initial,
        cash_balance=cash,
        invested_usd=invested,
        market_value=market_value,
        equity=equity,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        total_pnl=total_pnl,
        total_pnl_pct=(total_pnl / initial * 100.0) if initial else 0.0,
        daily_realized_pnl=daily_realized,
        daily_pnl=daily_realized + unrealized,
        open_positions=len(views),
        max_open_positions=limits.max_open_positions,
        daily_loss_limit=limits.daily_loss_limit_usd,
        daily_loss_used=max(0.0, -daily_realized),
        daily_loss_remaining=max(0.0, limits.daily_loss_limit_usd + daily_realized),
        halted=bool(account.is_halted),
        win_rate=(wins / len(closed) * 100.0) if closed else 0.0,
        closed_positions=len(closed),
        wins=wins,
        losses=losses,
        positions=views,
    )


async def performance_history(session: AsyncSession) -> dict[str, Any]:
    trading = TradingRepository(session)
    account = await trading.account()
    if account is None:
        raise RuntimeError("Paper account missing")
    days = await trading.daily_history(account.id, limit=90)
    closed = await trading.closed_positions(account.id)
    series = [
        {
            "day": row.day.isoformat(),
            "realized_pnl": _f(row.realized_pnl),
            "fees_paid": _f(row.fees_paid),
            "trades": row.trades,
            "entries": row.entries,
            "exits": row.exits,
            "halted": row.halted,
        }
        for row in reversed(days)
    ]
    cumulative = 0.0
    curve = []
    for point in series:
        cumulative += point["realized_pnl"]
        curve.append({"day": point["day"], "cumulative_realized": round(cumulative, 4)})

    total_trades = len(closed)
    wins = [p for p in closed if _f(p.realized_pnl) > 0]
    losses = [p for p in closed if _f(p.realized_pnl) < 0]
    avg_win = sum(_f(p.realized_pnl) for p in wins) / len(wins) if wins else 0.0
    avg_loss = sum(_f(p.realized_pnl) for p in losses) / len(losses) if losses else 0.0
    return {
        "daily": series,
        "realized_curve": curve,
        "trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / total_trades * 100.0) if total_trades else 0.0,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "profit_factor": round(abs(avg_win * len(wins) / (avg_loss * len(losses))), 3)
        if losses and avg_loss < 0
        else None,
        "best_trade": round(max((_f(p.realized_pnl) for p in closed), default=0.0), 4),
        "worst_trade": round(min((_f(p.realized_pnl) for p in closed), default=0.0), 4),
        "estimated": True,
    }


async def equity_series(session: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    history = await performance_history(session)
    account = await TradingRepository(session).account()
    initial = _f(account.initial_balance) if account else 0.0
    points = []
    for point in history["realized_curve"]:
        points.append(
            {"day": point["day"], "equity": round(initial + point["cumulative_realized"], 4)}
        )
    return points[-days:]


def current_day() -> date:
    return current_trading_day()

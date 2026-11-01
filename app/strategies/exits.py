"""Exit engine: stop-loss, trailing protection, momentum/liquidity/security exits
and the +50% / +100% profit targets. Pure and deterministic; every sell carries
a stable key so replays after a crash never double-sell.
"""

from __future__ import annotations

from app.strategies.config import StrategyConfig
from app.strategies.indicators import pct_change
from app.strategies.types import ExitAction, PositionView, SnapshotPoint


def _sell_all(reason: str, price: float, metrics: dict[str, float]) -> ExitAction:
    return ExitAction(
        action="SELL", reason=reason, exit_key=reason.lower(), ratio=1.0, price=price, metrics=metrics
    )


def evaluate_exit(
    position: PositionView,
    series: list[SnapshotPoint],
    cfg: StrategyConfig,
    *,
    security_status: str = "PASS",
    security_critical_unknown: bool = False,
) -> ExitAction | None:
    if not series or position.remaining_qty <= 0:
        return None

    last = series[-1]
    price = last.price
    pnl_pct = pct_change(price, position.entry_price)
    metrics = {
        "pnl_pct": round(pnl_pct, 3),
        "price": price,
        "liquidity_usd": round(last.liquidity, 2),
        "pct_m5": last.pct_m5,
        "pct_h1": last.pct_h1,
    }

    if pnl_pct <= -cfg.stop_loss_pct:
        return _sell_all("STOP_LOSS", price, metrics)

    if security_status == "FAIL" or security_critical_unknown:
        return _sell_all("SECURITY_BREAKDOWN", price, metrics)

    if (
        position.entry_liquidity_usd > 0
        and last.liquidity
        < position.entry_liquidity_usd * (1 - cfg.liquidity_collapse_pct / 100)
    ):
        return _sell_all("LIQUIDITY_COLLAPSE", price, metrics)

    if last.pct_m5 <= -cfg.momentum_breakdown_pct_m5 and last.pct_h1 < 0:
        return _sell_all("MOMENTUM_BREAKDOWN", price, metrics)

    if position.protection_armed and position.trail_high > 0:
        trail_floor = position.trail_high * (1 - cfg.trail_stop_pct / 100)
        if price <= trail_floor:
            metrics["trail_floor"] = round(trail_floor, 10)
            return _sell_all("TRAIL_STOP", price, metrics)

    if pnl_pct >= cfg.take_profit_full_pct:
        return _sell_all("TAKE_PROFIT_FULL", price, metrics)

    if pnl_pct >= cfg.take_profit_half_pct:
        return ExitAction(
            action="SELL",
            reason="TAKE_PROFIT_HALF",
            exit_key="take_profit_half",
            ratio=0.5,
            price=price,
            metrics=metrics,
        )

    if not position.protection_armed and pnl_pct >= cfg.protect_after_profit_pct:
        return ExitAction(
            action="UPDATE_STATE",
            reason="ARM_PROTECTION",
            exit_key="arm_protection",
            price=price,
            metrics=metrics,
            new_stop_price=position.entry_price,
            arm_protection=True,
        )

    return None

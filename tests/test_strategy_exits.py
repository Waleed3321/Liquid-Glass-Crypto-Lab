"""Strategy A entry gates and the exit engine (pure functions, no IO)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.strategies.config import StrategyConfig
from app.strategies.exits import evaluate_exit
from app.strategies.strategy_a import evaluate_entry
from app.strategies.types import EntryContext, PositionView, SnapshotPoint

START = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _series(
    prices: list[float],
    *,
    minutes: int = 1,
    liquidity: float = 50_000.0,
    volume_h1: float = 20_000.0,
    buys: int = 120,
    sells: int = 60,
    pct_m5: float = 1.0,
    pct_h1: float = 20.0,
) -> list[SnapshotPoint]:
    return [
        SnapshotPoint(
            ts=START + timedelta(minutes=index * minutes),
            price=price,
            liquidity=liquidity,
            volume_m5=volume_h1 / 12,
            volume_h1=volume_h1,
            buys_h1=buys,
            sells_h1=sells,
            buys_m5=12,
            sells_m5=6,
            pct_m5=pct_m5 if index == len(prices) - 1 else 0.0,
            pct_h1=pct_h1 if index == len(prices) - 1 else 0.0,
        )
        for index, price in enumerate(prices)
    ]


GOLDEN_PRICES = [
    1.00, 1.02, 1.04, 1.06, 1.09, 1.12, 1.15, 1.18, 1.20, 1.18, 1.15, 1.12, 1.10, 1.11,
]


def _ctx(**overrides) -> EntryContext:
    base = dict(
        score=78.0,
        confidence=0.8,
        security_status="PASS",
        security_eligible=True,
        critical_unknown=0,
        warning_count=0,
        roundtrip_cost_pct=0.9,
        available_cash=10.0,
        max_position_usd=2.5,
        cooldown_active=False,
    )
    base.update(overrides)
    return EntryContext(**base)


def _cfg(**overrides) -> StrategyConfig:
    return StrategyConfig(**overrides) if overrides else StrategyConfig()


def test_golden_pullback_series_enters_with_capped_size():
    signal = evaluate_entry(_series(GOLDEN_PRICES), _ctx(), _cfg())
    assert signal.accepted is True
    assert signal.reason_codes == ["ENTER"]
    assert signal.size_usd == pytest.approx(2.5)
    assert signal.strength >= 0.55
    assert 3.0 <= signal.metrics["drawdown_pct"] <= 12.0
    assert signal.metrics["observation_minutes"] >= 10


def test_vertical_five_minute_candle_is_rejected():
    signal = evaluate_entry(_series(GOLDEN_PRICES, pct_m5=25.0), _ctx(), _cfg())
    assert signal.accepted is False
    assert "VERTICAL_CANDLE" in signal.reason_codes


def test_price_far_above_sma_is_rejected():
    prices = [1.0] * 11 + [1.6, 1.6, 1.6]
    signal = evaluate_entry(_series(prices, pct_h1=20.0), _ctx(), _cfg())
    assert "VERTICAL_CANDLE" in signal.reason_codes


def test_flat_market_has_no_trend():
    prices = [1.0, 1.001, 1.0, 1.001, 1.0, 1.001, 1.0, 1.001, 1.0, 1.001, 1.0, 1.001]
    signal = evaluate_entry(_series(prices, pct_h1=0.5), _ctx(), _cfg())
    assert signal.accepted is False
    assert "NO_TREND" in signal.reason_codes


def test_monotonic_run_has_no_pullback():
    prices = [1.0 + index * 0.02 for index in range(14)]
    signal = evaluate_entry(_series(prices, pct_h1=20.0), _ctx(), _cfg())
    assert signal.accepted is False
    assert "NO_PULLBACK" in signal.reason_codes


def test_deep_pullback_is_rejected():
    prices = [1.0, 1.1, 1.2, 1.3, 1.4, 1.45, 1.35, 1.25, 1.15, 1.0, 0.95, 0.9]
    signal = evaluate_entry(_series(prices, pct_h1=20.0), _ctx(), _cfg())
    assert "PULLBACK_TOO_DEEP" in signal.reason_codes


def test_insufficient_observation_is_rejected():
    signal = evaluate_entry(_series([1.0, 1.02, 1.01]), _ctx(), _cfg())
    assert signal.accepted is False
    assert "INSUFFICIENT_OBSERVATION" in signal.reason_codes
    assert signal.metrics["snapshots"] == 3


def test_observation_gap_is_rejected():
    base = _series(GOLDEN_PRICES)
    series = [
        SnapshotPoint(
            ts=point.ts + timedelta(minutes=5 if index >= 7 else 0),
            price=point.price,
            liquidity=point.liquidity,
            volume_m5=point.volume_m5,
            volume_h1=point.volume_h1,
            buys_h1=point.buys_h1,
            sells_h1=point.sells_h1,
            pct_m5=point.pct_m5,
            pct_h1=point.pct_h1,
        )
        for index, point in enumerate(base)
    ]
    signal = evaluate_entry(series, _ctx(), _cfg())
    assert "INSUFFICIENT_OBSERVATION" in signal.reason_codes
    assert signal.metrics["missing_gap"] is True


def test_observation_uses_only_data_after_a_restart_gap():
    """History before a scanner restart must not poison the newest run."""
    stale = _series(GOLDEN_PRICES[:2])
    stale = [
        SnapshotPoint(
            ts=point.ts - timedelta(minutes=20),
            price=point.price,
            liquidity=point.liquidity,
            volume_m5=point.volume_m5,
            volume_h1=point.volume_h1,
            buys_h1=point.buys_h1,
            sells_h1=point.sells_h1,
            pct_m5=point.pct_m5,
            pct_h1=point.pct_h1,
        )
        for point in stale
    ]
    fresh = _series(GOLDEN_PRICES)
    signal = evaluate_entry([*stale, *fresh], _ctx(), _cfg())
    assert signal.accepted is True
    assert signal.metrics["snapshots"] == len(fresh)
    assert signal.metrics["max_gap_seconds"] <= 150


def test_security_gate_and_unknown_fields_reject():
    blocked = evaluate_entry(_series(GOLDEN_PRICES), _ctx(security_eligible=False), _cfg())
    assert "SECURITY_GATE" in blocked.reason_codes

    incomplete = evaluate_entry(_series(GOLDEN_PRICES), _ctx(critical_unknown=1), _cfg())
    assert "SECURITY_INCOMPLETE" in incomplete.reason_codes


def test_low_score_low_confidence_and_high_cost_reject():
    low_score = evaluate_entry(_series(GOLDEN_PRICES), _ctx(score=40.0), _cfg())
    assert "LOW_SCORE" in low_score.reason_codes

    low_conf = evaluate_entry(_series(GOLDEN_PRICES), _ctx(confidence=0.3), _cfg())
    assert "LOW_CONFIDENCE" in low_conf.reason_codes

    costly = evaluate_entry(_series(GOLDEN_PRICES), _ctx(roundtrip_cost_pct=4.0), _cfg())
    assert "HIGH_COST" in costly.reason_codes


def test_thin_liquidity_and_deterioration_reject():
    thin = evaluate_entry(_series(GOLDEN_PRICES, liquidity=2_000.0), _ctx(), _cfg())
    assert "THIN_LIQUIDITY" in thin.reason_codes

    series = _series(GOLDEN_PRICES)
    series[0] = SnapshotPoint(
        ts=series[0].ts,
        price=series[0].price,
        liquidity=100_000.0,
        volume_h1=series[0].volume_h1,
        buys_h1=series[0].buys_h1,
        sells_h1=series[0].sells_h1,
    )
    deteriorated = evaluate_entry(series, _ctx(), _cfg())
    assert "LIQUIDITY_DETERIORATION" in deteriorated.reason_codes


def test_fomo_and_cooldown_reject():
    fomo = evaluate_entry(_series(GOLDEN_PRICES, buys=600, sells=50), _ctx(), _cfg())
    assert "FOMO_ACTIVITY" in fomo.reason_codes

    cooldown = evaluate_entry(_series(GOLDEN_PRICES), _ctx(cooldown_active=True), _cfg())
    assert "COOLDOWN" in cooldown.reason_codes


def test_no_edge_when_available_cash_is_below_minimum():
    signal = evaluate_entry(_series(GOLDEN_PRICES), _ctx(available_cash=0.4), _cfg())
    assert "NO_EDGE" in signal.reason_codes
    assert signal.size_usd == pytest.approx(0.4)


# -- exits --------------------------------------------------------------------
def _position(**overrides) -> PositionView:
    base = dict(
        position_id=1,
        entry_price=1.0,
        qty=2.5,
        remaining_qty=2.5,
        peak_price=1.0,
        trail_high=1.0,
        protection_armed=False,
        entry_liquidity_usd=50_000.0,
        invested_usd=2.5,
        entry_fees=0.02,
    )
    base.update(overrides)
    return PositionView(**base)


def _point(price: float, *, pct_m5: float = 0.0, pct_h1: float = 5.0,
           liquidity: float = 50_000.0) -> SnapshotPoint:
    return SnapshotPoint(
        ts=START, price=price, liquidity=liquidity, pct_m5=pct_m5, pct_h1=pct_h1
    )


def test_stop_loss_fires_at_eighteen_percent():
    action = evaluate_exit(_position(), [_point(0.81)], _cfg())
    assert action is not None
    assert action.reason == "STOP_LOSS"
    assert action.ratio == 1.0
    assert action.exit_key == "stop_loss"


def test_take_profit_half_sells_fifty_percent_at_plus_fifty():
    action = evaluate_exit(_position(), [_point(1.51)], _cfg())
    assert action is not None
    assert action.reason == "TAKE_PROFIT_HALF"
    assert action.ratio == 0.5
    assert action.exit_key == "take_profit_half"


def test_take_profit_full_closes_at_plus_hundred():
    action = evaluate_exit(_position(), [_point(2.0)], _cfg())
    assert action is not None
    assert action.reason == "TAKE_PROFIT_FULL"
    assert action.ratio == 1.0


def test_plus_thirty_arms_protection_without_selling():
    action = evaluate_exit(_position(), [_point(1.31)], _cfg())
    assert action is not None
    assert action.action == "UPDATE_STATE"
    assert action.arm_protection is True
    assert action.new_stop_price == pytest.approx(1.0)


def test_trailing_stop_fires_after_arming():
    armed = _position(protection_armed=True, peak_price=1.6, trail_high=1.6)
    action = evaluate_exit(armed, [_point(1.40)], _cfg())
    assert action is not None
    assert action.reason == "TRAIL_STOP"
    assert action.ratio == 1.0


def test_security_breakdown_exits_position():
    action = evaluate_exit(_position(), [_point(1.0)], _cfg(), security_status="FAIL")
    assert action is not None
    assert action.reason == "SECURITY_BREAKDOWN"


def test_liquidity_collapse_exits_position():
    action = evaluate_exit(_position(), [_point(1.0, liquidity=20_000.0)], _cfg())
    assert action is not None
    assert action.reason == "LIQUIDITY_COLLAPSE"


def test_momentum_breakdown_exits_position():
    action = evaluate_exit(_position(), [_point(1.0, pct_m5=-10.0, pct_h1=-1.0)], _cfg())
    assert action is not None
    assert action.reason == "MOMENTUM_BREAKDOWN"


def test_no_exit_inside_normal_band():
    assert evaluate_exit(_position(), [_point(1.2)], _cfg()) is None
    assert evaluate_exit(_position(remaining_qty=0.0), [_point(1.0)], _cfg()) is None
    assert evaluate_exit(_position(), [], _cfg()) is None

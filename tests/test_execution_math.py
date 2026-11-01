"""Execution maths: impact, slippage, fees and quote rejection boundaries."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.clock import utc_now
from app.execution.fees import buy_fees, dex_fee_usd, network_fee_usd, sell_fees, tax_fee_usd
from app.execution.impact import impact_within_limit, price_impact_pct, quote_reserve_usd
from app.execution.quote import QuoteRequest, build_buy_quote
from app.execution.simulator import estimate_roundtrip_cost_pct, simulate_buy, simulate_sell
from app.execution.slippage import slippage_pct
from app.strategies.config import StrategyConfig


def _quote(**overrides) -> QuoteRequest:
    base = dict(
        chain="solana",
        notional_usd=2.5,
        price_usd=0.001,
        liquidity_usd=50_000.0,
        snapshot_ts=utc_now(),
        buy_tax_pct=0.0,
        sell_tax_pct=0.0,
        recent_prices=[0.001],
    )
    base.update(overrides)
    return QuoteRequest(**base)


def test_impact_formula_uses_half_the_pool():
    assert quote_reserve_usd(10_000) == pytest.approx(5_000)
    assert price_impact_pct(50, 10_000) == pytest.approx(1.0)
    assert price_impact_pct(25, 10_000) == pytest.approx(0.5)
    assert price_impact_pct(1, 0) == 100.0


def test_impact_boundary_is_one_percent():
    assert impact_within_limit(49.999, 10_000, 1.0) is True
    assert impact_within_limit(50.0001, 10_000, 1.0) is False


def test_quote_rejects_impact_over_limit():
    quote = build_buy_quote(_quote(notional_usd=60.0, liquidity_usd=10_000.0), StrategyConfig())
    assert quote.reject_code == "IMPACT_LIMIT"
    assert quote.ok is False


def test_quote_accepts_impact_just_below_limit():
    quote = build_buy_quote(_quote(notional_usd=25.0, liquidity_usd=5_000.0), StrategyConfig())
    assert quote.impact_pct == pytest.approx(1.0)
    assert quote.reject_code is None
    assert quote.ok is True


def test_slippage_is_base_plus_impact_plus_volatility():
    assert slippage_pct(0.0, pct_m5=0.0) == pytest.approx(0.5)
    assert slippage_pct(1.0, pct_m5=0.0) == pytest.approx(1.0)
    assert slippage_pct(0.0, pct_m5=10.0) == pytest.approx(0.7)
    assert slippage_pct(0.0, pct_m5=80.0) == pytest.approx(1.25)


def test_buy_simulation_applies_slippage_impact_and_tax():
    sim = simulate_buy(
        chain="solana",
        notional_usd=2.5,
        price_usd=1.0,
        liquidity_usd=25_000.0,
        buy_tax_pct=2.0,
    )
    expected_impact = 2.5 / 12_500 * 100.0
    expected_slip = 0.5 + 0.5 * expected_impact
    expected_price = 1.0 * (1 + expected_impact / 100 + expected_slip / 100)
    assert sim.impact_pct == pytest.approx(expected_impact)
    assert sim.slippage_pct == pytest.approx(expected_slip)
    assert sim.exec_price == pytest.approx(expected_price, rel=1e-9)
    assert sim.fees.tax_usd == pytest.approx(0.05)
    assert sim.qty == pytest.approx(2.5 / expected_price * 0.98)
    assert sim.cash_debit == pytest.approx(2.5 + sim.fees.network_usd + sim.fees.dex_usd)


def test_sell_simulation_reduces_proceeds_by_costs():
    sim = simulate_sell(
        chain="bsc",
        qty=1000.0,
        price_usd=0.01,
        liquidity_usd=20_000.0,
        sell_tax_pct=1.0,
    )
    assert sim.exec_price < 0.01
    assert sim.gross_usd == pytest.approx(sim.qty_net * sim.exec_price)
    assert sim.proceeds_usd == pytest.approx(
        sim.gross_usd - sim.fees.network_usd - sim.fees.dex_usd
    )
    assert sim.proceeds_usd < sim.gross_usd


def test_fee_breakdown_matches_configured_defaults():
    buy = buy_fees("solana", 2.5, 0.0)
    assert buy.network_usd == pytest.approx(0.012)
    assert buy.dex_usd == pytest.approx(2.5 * 0.0025)
    assert buy.tax_usd == 0.0
    assert buy.total_usd == pytest.approx(0.012 + 0.00625)

    bsc = buy_fees("bsc", 2.5, 1.0)
    assert bsc.network_usd >= 0.03
    assert bsc.tax_usd == pytest.approx(0.025)

    assert network_fee_usd("bsc") == pytest.approx(max(0.03, 210_000 * 0.1e-9 * 600))
    assert dex_fee_usd(100.0) == pytest.approx(0.25)
    assert tax_fee_usd(100.0, None) == 0.0
    assert sell_fees("solana", 10.0, 0.0).dex_usd == pytest.approx(0.025)


def test_roundtrip_cost_is_within_strategy_budget():
    cost = estimate_roundtrip_cost_pct(
        chain="solana",
        notional_usd=2.5,
        liquidity_usd=50_000.0,
        buy_tax_pct=0.0,
        sell_tax_pct=0.0,
    )
    assert 0.5 < cost < 3.0


def test_quote_rejections_cover_stale_thin_and_unknown_tax():
    stale = build_buy_quote(
        _quote(snapshot_ts=utc_now() - timedelta(seconds=600)), StrategyConfig()
    )
    assert stale.reject_code == "STALE_DATA"

    thin = build_buy_quote(_quote(liquidity_usd=4_000.0), StrategyConfig())
    assert thin.reject_code == "THIN_LIQUIDITY"

    deviated = build_buy_quote(_quote(recent_prices=[0.002, 0.002, 0.002]), StrategyConfig())
    assert deviated.reject_code == "STALE_DATA"

    unknown_tax = build_buy_quote(
        _quote(buy_tax_pct=None, sell_tax_pct=None, buy_tax_known=False, sell_tax_known=False),
        StrategyConfig(),
    )
    assert unknown_tax.reject_code == "SECURITY_INCOMPLETE"

    failed = build_buy_quote(_quote(security_status="FAIL"), StrategyConfig())
    assert failed.reject_code == "SECURITY_REJECTED"

    invalid = build_buy_quote(_quote(notional_usd=0.0), StrategyConfig())
    assert invalid.reject_code == "INVALID_NOTIONAL"

"""Paper fill simulation: entry/exit prices, fees, taxes, slippage and impact."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.execution.fees import FeeBreakdown, buy_fees, sell_fees
from app.execution.impact import price_impact_pct
from app.execution.slippage import slippage_pct
from app.strategies.config import StrategyConfig


@dataclass(slots=True)
class SimulatedBuy:
    exec_price: float
    qty: float
    notional: float
    cash_debit: float
    fees: FeeBreakdown
    impact_pct: float
    slippage_pct: float
    effective_entry_price: float


@dataclass(slots=True)
class SimulatedSell:
    exec_price: float
    qty_sold: float
    qty_net: float
    gross_usd: float
    proceeds_usd: float
    fees: FeeBreakdown
    impact_pct: float
    slippage_pct: float


def simulate_buy(
    *,
    chain: str,
    notional_usd: float,
    price_usd: float,
    liquidity_usd: float,
    buy_tax_pct: float | None,
    pct_m5: float = 0.0,
    cfg: StrategyConfig | None = None,
) -> SimulatedBuy:
    impact = price_impact_pct(notional_usd, liquidity_usd)
    slip = slippage_pct(
        impact,
        base_slippage_bps=settings.base_slippage_bps,
        impact_multiplier=settings.slippage_impact_multiplier,
        pct_m5=pct_m5,
    )
    exec_price = price_usd * (1 + impact / 100.0 + slip / 100.0)
    qty_gross = notional_usd / exec_price if exec_price > 0 else 0.0
    tax_pct = max(0.0, buy_tax_pct or 0.0)
    qty = qty_gross * (1 - tax_pct / 100.0)
    fees = buy_fees(chain, notional_usd, tax_pct)
    cash_debit = round(notional_usd + fees.network_usd + fees.dex_usd, 10)
    effective_entry = round(notional_usd / qty, 12) if qty > 0 else 0.0
    return SimulatedBuy(
        exec_price=round(exec_price, 12),
        qty=qty,
        notional=notional_usd,
        cash_debit=cash_debit,
        fees=fees,
        impact_pct=impact,
        slippage_pct=slip,
        effective_entry_price=effective_entry,
    )


def simulate_sell(
    *,
    chain: str,
    qty: float,
    price_usd: float,
    liquidity_usd: float,
    sell_tax_pct: float | None,
    pct_m5: float = 0.0,
    cfg: StrategyConfig | None = None,
) -> SimulatedSell:
    gross_market = qty * price_usd
    impact = price_impact_pct(gross_market, liquidity_usd)
    slip = slippage_pct(
        impact,
        base_slippage_bps=settings.base_slippage_bps,
        impact_multiplier=settings.slippage_impact_multiplier,
        pct_m5=pct_m5,
    )
    exec_price = max(0.0, price_usd * (1 - impact / 100.0 - slip / 100.0))
    tax_pct = max(0.0, sell_tax_pct or 0.0)
    qty_net = qty * (1 - tax_pct / 100.0)
    gross_usd = qty_net * exec_price
    fees = sell_fees(chain, gross_usd, tax_pct)
    proceeds = max(0.0, gross_usd - fees.network_usd - fees.dex_usd)
    return SimulatedSell(
        exec_price=round(exec_price, 12),
        qty_sold=qty,
        qty_net=qty_net,
        gross_usd=gross_usd,
        proceeds_usd=round(proceeds, 10),
        fees=fees,
        impact_pct=impact,
        slippage_pct=slip,
    )


def estimate_roundtrip_cost_pct(
    *,
    chain: str,
    notional_usd: float,
    liquidity_usd: float,
    buy_tax_pct: float | None,
    sell_tax_pct: float | None,
    pct_m5: float = 0.0,
) -> float:
    buy = simulate_buy(
        chain=chain,
        notional_usd=notional_usd,
        price_usd=1.0,
        liquidity_usd=liquidity_usd,
        buy_tax_pct=buy_tax_pct,
        pct_m5=pct_m5,
    )
    sell = simulate_sell(
        chain=chain,
        qty=buy.qty,
        price_usd=1.0,
        liquidity_usd=liquidity_usd,
        sell_tax_pct=sell_tax_pct,
        pct_m5=pct_m5,
    )
    spent = buy.cash_debit
    if spent <= 0:
        return 100.0
    return round((1 - sell.proceeds_usd / spent) * 100.0, 4)

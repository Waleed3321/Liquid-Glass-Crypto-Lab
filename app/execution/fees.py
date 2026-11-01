"""Estimated execution costs.

Every number produced here is a simulation estimate: the platform never
submits a real transaction. Values are stored on each fill and labelled in the
UI so P&L is transparent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(slots=True)
class FeeBreakdown:
    network_usd: float
    dex_usd: float
    tax_usd: float

    @property
    def total_usd(self) -> float:
        return round(self.network_usd + self.dex_usd + self.tax_usd, 10)


def network_fee_usd(chain: str) -> float:
    if chain == "solana":
        base = max(settings.solana_network_fee_usd, 0.01)
        return round(base + max(settings.solana_priority_fee_usd, 0.0), 10)
    gas = (
        settings.bsc_gas_units
        * settings.bsc_gas_price_gwei
        * 1e-9
        * max(settings.bnb_price_usd, 0.0)
    )
    return round(max(gas, settings.bsc_network_fee_usd), 10)


def dex_fee_usd(notional_usd: float) -> float:
    return round(max(0.0, notional_usd) * settings.dex_fee_pct / 100.0, 10)


def tax_fee_usd(notional_usd: float, tax_pct: float | None) -> float:
    if not tax_pct or tax_pct <= 0:
        return 0.0
    return round(max(0.0, notional_usd) * tax_pct / 100.0, 10)


def buy_fees(chain: str, notional_usd: float, buy_tax_pct: float | None) -> FeeBreakdown:
    return FeeBreakdown(
        network_usd=network_fee_usd(chain),
        dex_usd=dex_fee_usd(notional_usd),
        tax_usd=tax_fee_usd(notional_usd, buy_tax_pct),
    )


def sell_fees(chain: str, gross_usd: float, sell_tax_pct: float | None) -> FeeBreakdown:
    return FeeBreakdown(
        network_usd=network_fee_usd(chain),
        dex_usd=dex_fee_usd(gross_usd),
        tax_usd=tax_fee_usd(gross_usd, sell_tax_pct),
    )

"""Constant-product price-impact approximation.

For a constant-product pool the quote reserve is roughly half of the reported
liquidity, so a trade of ``A`` USD moves the average price by about ``A / (L/2)``.
The result is an estimate, always displayed as such.
"""

from __future__ import annotations


def quote_reserve_usd(liquidity_usd: float) -> float:
    return max(0.0, liquidity_usd) / 2.0


def price_impact_pct(notional_usd: float, liquidity_usd: float) -> float:
    reserve = quote_reserve_usd(liquidity_usd)
    if reserve <= 0:
        return 100.0
    return notional_usd / reserve * 100.0


def impact_within_limit(notional_usd: float, liquidity_usd: float, max_impact_pct: float) -> bool:
    return price_impact_pct(notional_usd, liquidity_usd) <= max_impact_pct

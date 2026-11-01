"""Slippage estimate: base buffer + impact-linked component + volatility addon."""

from __future__ import annotations

from app.strategies.indicators import clamp


def slippage_pct(
    impact_pct: float,
    *,
    base_slippage_bps: float = 50.0,
    impact_multiplier: float = 0.5,
    pct_m5: float = 0.0,
) -> float:
    base = max(0.0, base_slippage_bps) / 100.0
    impact_component = max(0.0, impact_multiplier) * max(0.0, impact_pct)
    volatility_component = clamp(abs(pct_m5) * 0.02, 0.0, 0.75)
    return round(base + impact_component + volatility_component, 6)

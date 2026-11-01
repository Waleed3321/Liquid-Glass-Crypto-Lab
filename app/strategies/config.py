"""User-tunable strategy and risk configuration.

Hard caps mirror the product rules: users may tighten limits through the
Settings page but can never loosen them past the specification.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class StrategyConfig(BaseModel):
    # Observation
    min_observation_minutes: float = Field(default=10.0, ge=1.0, le=120.0)
    min_snapshots: int = Field(default=8, ge=3, le=120)
    max_snapshot_gap_seconds: int = Field(default=150, ge=60, le=900)

    # Entry gates
    entry_score_threshold: float = Field(default=62.0, ge=0.0, le=100.0)
    entry_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    min_signal_strength: float = Field(default=0.55, ge=0.0, le=1.0)

    # Trend / pullback
    trend_min_pct_h1: float = Field(default=3.0, ge=0.0, le=50.0)
    trend_max_pct_h1: float = Field(default=40.0, ge=1.0, le=200.0)
    pullback_min_pct: float = Field(default=3.0, ge=0.5, le=30.0)
    pullback_max_pct: float = Field(default=12.0, ge=1.0, le=50.0)
    stabilization_band_pct: float = Field(default=3.0, ge=0.5, le=15.0)
    max_pct_m5: float = Field(default=15.0, ge=1.0, le=100.0)
    sma_window: int = Field(default=10, ge=3, le=60)
    max_price_vs_sma_pct: float = Field(default=15.0, ge=1.0, le=100.0)

    # Liquidity / activity
    min_liquidity_usd: float = Field(default=8000.0, ge=1000.0, le=5_000_000.0)
    liquidity_deterioration_pct: float = Field(default=30.0, ge=5.0, le=90.0)
    min_turnover_h1: float = Field(default=0.05, ge=0.0, le=10.0)
    min_buy_sell_ratio: float = Field(default=1.1, ge=0.1, le=10.0)
    max_buy_sell_ratio: float = Field(default=4.0, ge=1.0, le=20.0)

    # Sizing (hard caps)
    min_position_usd: float = Field(default=1.0, ge=0.1, le=10.0)
    max_position_usd: float = Field(default=2.5, gt=0.0, le=2.5)
    max_open_positions: int = Field(default=3, ge=1, le=3)
    daily_loss_limit_usd: float = Field(default=0.5, gt=0.0, le=0.5)
    max_price_impact_pct: float = Field(default=1.0, gt=0.0, le=1.0)
    max_price_age_seconds: int = Field(default=120, ge=10, le=3600)

    # Exit rules
    stop_loss_pct: float = Field(default=18.0, ge=1.0, le=90.0)
    trail_stop_pct: float = Field(default=12.0, ge=1.0, le=50.0)
    protect_after_profit_pct: float = Field(default=30.0, ge=5.0, le=100.0)
    take_profit_half_pct: float = Field(default=50.0, ge=10.0, le=200.0)
    take_profit_full_pct: float = Field(default=100.0, ge=20.0, le=500.0)
    momentum_breakdown_pct_m5: float = Field(default=8.0, ge=1.0, le=50.0)
    liquidity_collapse_pct: float = Field(default=50.0, ge=10.0, le=95.0)

    # Costs and cooldowns
    max_roundtrip_cost_pct: float = Field(default=3.0, ge=0.1, le=20.0)
    cooldown_after_exit_minutes: int = Field(default=45, ge=1, le=720)

    # Strategy version (exposed in decisions)
    version: str = "A-1.0"

    @model_validator(mode="after")
    def _validate_ranges(self) -> StrategyConfig:
        if self.pullback_min_pct >= self.pullback_max_pct:
            raise ValueError("pullback_min_pct must be lower than pullback_max_pct")
        if self.trend_min_pct_h1 >= self.trend_max_pct_h1:
            raise ValueError("trend_min_pct_h1 must be lower than trend_max_pct_h1")
        if self.min_buy_sell_ratio >= self.max_buy_sell_ratio:
            raise ValueError("min_buy_sell_ratio must be lower than max_buy_sell_ratio")
        if self.take_profit_half_pct >= self.take_profit_full_pct:
            raise ValueError("take_profit_half_pct must be lower than take_profit_full_pct")
        if self.min_position_usd > self.max_position_usd:
            raise ValueError("min_position_usd cannot exceed max_position_usd")
        return self

    def merged(self, overrides: dict[str, Any] | None) -> StrategyConfig:
        if not overrides:
            return self
        data = self.model_dump()
        allowed = set(StrategyConfig.model_fields)
        for key, value in overrides.items():
            if key in allowed:
                data[key] = value
        return StrategyConfig(**data)

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump()

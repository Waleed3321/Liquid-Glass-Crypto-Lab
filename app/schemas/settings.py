"""Settings update models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StrategySettingsIn(BaseModel):
    min_observation_minutes: float | None = Field(default=None, ge=1, le=120)
    min_snapshots: int | None = Field(default=None, ge=3, le=120)
    max_snapshot_gap_seconds: int | None = Field(default=None, ge=60, le=900)
    entry_score_threshold: float | None = Field(default=None, ge=0, le=100)
    entry_confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    min_signal_strength: float | None = Field(default=None, ge=0, le=1)
    trend_min_pct_h1: float | None = Field(default=None, ge=0, le=50)
    trend_max_pct_h1: float | None = Field(default=None, ge=1, le=200)
    pullback_min_pct: float | None = Field(default=None, ge=0.5, le=30)
    pullback_max_pct: float | None = Field(default=None, ge=1, le=50)
    stabilization_band_pct: float | None = Field(default=None, ge=0.5, le=15)
    max_pct_m5: float | None = Field(default=None, ge=1, le=100)
    sma_window: int | None = Field(default=None, ge=3, le=60)
    max_price_vs_sma_pct: float | None = Field(default=None, ge=1, le=100)
    min_liquidity_usd: float | None = Field(default=None, ge=1000, le=5_000_000)
    liquidity_deterioration_pct: float | None = Field(default=None, ge=5, le=90)
    min_turnover_h1: float | None = Field(default=None, ge=0, le=10)
    min_buy_sell_ratio: float | None = Field(default=None, ge=0.1, le=10)
    max_buy_sell_ratio: float | None = Field(default=None, ge=1, le=20)
    min_position_usd: float | None = Field(default=None, ge=0.1, le=10)
    max_position_usd: float | None = Field(default=None, gt=0, le=2.5)
    max_open_positions: int | None = Field(default=None, ge=1, le=3)
    daily_loss_limit_usd: float | None = Field(default=None, gt=0, le=0.5)
    max_price_impact_pct: float | None = Field(default=None, gt=0, le=1)
    max_price_age_seconds: int | None = Field(default=None, ge=10, le=3600)
    stop_loss_pct: float | None = Field(default=None, ge=1, le=90)
    trail_stop_pct: float | None = Field(default=None, ge=1, le=50)
    protect_after_profit_pct: float | None = Field(default=None, ge=5, le=100)
    take_profit_half_pct: float | None = Field(default=None, ge=10, le=200)
    take_profit_full_pct: float | None = Field(default=None, ge=20, le=500)
    momentum_breakdown_pct_m5: float | None = Field(default=None, ge=1, le=50)
    liquidity_collapse_pct: float | None = Field(default=None, ge=10, le=95)
    max_roundtrip_cost_pct: float | None = Field(default=None, ge=0.1, le=20)
    cooldown_after_exit_minutes: int | None = Field(default=None, ge=1, le=720)

    def overrides(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


class ScannerSettingsIn(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=30, le=300)
    discovery_window_hours: float | None = Field(default=None, ge=1, le=24)

    def overrides(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


class NotificationSettingsIn(BaseModel):
    enabled: bool | None = None
    min_score_for_alert: float | None = Field(default=None, ge=0, le=100)
    notify_security_warnings: bool | None = None
    notify_entries: bool | None = None
    notify_exits: bool | None = None

    def overrides(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


class SettingsIn(BaseModel):
    strategy: StrategySettingsIn | None = None
    scanner: ScannerSettingsIn | None = None
    notifications: NotificationSettingsIn | None = None

"""Risk limits derived from settings and the active strategy configuration."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.strategies.config import StrategyConfig


@dataclass(frozen=True, slots=True)
class RiskLimits:
    initial_balance_usd: float
    max_open_positions: int
    max_position_usd: float
    daily_loss_limit_usd: float
    max_price_impact_pct: float
    max_price_age_seconds: int

    @classmethod
    def from_config(cls, cfg: StrategyConfig | None = None) -> RiskLimits:
        cfg = cfg or StrategyConfig()
        return cls(
            initial_balance_usd=settings.initial_balance_usd,
            max_open_positions=min(settings.max_open_positions, cfg.max_open_positions, 3),
            max_position_usd=min(settings.max_position_usd, cfg.max_position_usd, 2.5),
            daily_loss_limit_usd=min(
                settings.daily_loss_limit_usd, cfg.daily_loss_limit_usd, 0.5
            ),
            max_price_impact_pct=min(
                settings.max_price_impact_pct, cfg.max_price_impact_pct, 1.0
            ),
            max_price_age_seconds=min(
                settings.max_price_age_seconds, cfg.max_price_age_seconds
            ),
        )

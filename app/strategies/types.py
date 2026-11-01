"""Plain data structures used by the pure strategy functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SnapshotPoint:
    ts: datetime
    price: float
    liquidity: float
    volume_m5: float = 0.0
    volume_h1: float = 0.0
    buys_h1: int = 0
    sells_h1: int = 0
    buys_m5: int = 0
    sells_m5: int = 0
    pct_m5: float = 0.0
    pct_h1: float = 0.0


@dataclass(slots=True)
class EntryContext:
    score: float
    confidence: float
    security_status: str
    security_eligible: bool
    critical_unknown: int = 0
    warning_count: int = 0
    roundtrip_cost_pct: float = 0.0
    available_cash: float = 0.0
    max_position_usd: float = 2.5
    cooldown_active: bool = False
    now: datetime | None = None


@dataclass(slots=True)
class EntrySignal:
    action: str  # ENTER | REJECT
    strength: float
    reason_codes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    size_usd: float = 0.0

    @property
    def accepted(self) -> bool:
        return self.action == "ENTER"


@dataclass(slots=True)
class PositionView:
    position_id: int
    entry_price: float
    qty: float
    remaining_qty: float
    peak_price: float
    trail_high: float
    protection_armed: bool
    entry_liquidity_usd: float
    invested_usd: float
    entry_fees: float = 0.0


@dataclass(slots=True)
class ExitAction:
    action: str  # SELL | UPDATE_STATE
    reason: str
    exit_key: str
    qty: float = 0.0
    ratio: float = 0.0
    price: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    new_stop_price: float | None = None
    arm_protection: bool = False

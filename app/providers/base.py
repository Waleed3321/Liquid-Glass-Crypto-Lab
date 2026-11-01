"""Normalised provider contracts.

Adapters translate third-party payloads into these dataclasses so the scanner
and strategy never depend on a specific API shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.models.enums import SecurityStatus


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class PoolDiscovery:
    chain: str
    token_address: str
    pool_address: str
    symbol: str
    name: str
    dex_id: str | None
    quote_symbol: str | None
    created_at: datetime | None
    price_usd: float
    liquidity_usd: float
    market_cap_usd: float
    fdv_usd: float
    volume: dict[str, float] = field(default_factory=dict)
    txns: dict[str, dict[str, int]] = field(default_factory=dict)
    price_change: dict[str, float] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    source: str = "geckoterminal"


@dataclass(slots=True)
class MarketQuote:
    chain: str
    token_address: str
    pool_address: str
    symbol: str = ""
    name: str = ""
    dex_id: str | None = None
    quote_symbol: str | None = None
    price_usd: float = 0.0
    liquidity_usd: float = 0.0
    market_cap_usd: float = 0.0
    fdv_usd: float = 0.0
    volume: dict[str, float] = field(default_factory=dict)
    txns: dict[str, dict[str, int]] = field(default_factory=dict)
    price_change: dict[str, float] = field(default_factory=dict)
    created_at: datetime | None = None
    image_url: str | None = None
    website_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    source: str = "dexscreener"


@dataclass(slots=True)
class SecurityField:
    name: str
    status: str
    value: Any = None
    reason: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "value": self.value,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(slots=True)
class SecurityResult:
    chain: str
    token_address: str
    provider: str
    fields: dict[str, SecurityField] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    available: bool = True

    def status_of(self, name: str) -> str:
        item = self.fields.get(name)
        return item.status if item else SecurityStatus.UNKNOWN.value

    def value_of(self, name: str, default: Any = None) -> Any:
        item = self.fields.get(name)
        return item.value if item is not None else default


class DiscoveryProvider(Protocol):
    async def new_pools(self, chain: str, pages: int = 2) -> list[PoolDiscovery]: ...


class MarketProvider(Protocol):
    async def quotes(self, addresses: list[str]) -> list[MarketQuote]: ...


class SecurityProvider(Protocol):
    async def check(self, chain: str, token_address: str) -> SecurityResult | None: ...


@dataclass(slots=True)
class NotificationMessage:
    title: str
    body: str
    severity: str = "INFO"
    fields: list[tuple[str, str]] = field(default_factory=list)
    url: str | None = None

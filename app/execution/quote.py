"""Read-only quote construction with staleness and impact validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.clock import ensure_utc, utc_now
from app.execution.fees import buy_fees
from app.execution.impact import price_impact_pct
from app.execution.slippage import slippage_pct
from app.models.enums import SecurityStatus
from app.strategies.config import StrategyConfig
from app.strategies.indicators import median

MIN_LIQUIDITY_USD = 5000.0
MAX_PRICE_DEVIATION_PCT = 8.0


@dataclass(slots=True)
class QuoteRequest:
    chain: str
    notional_usd: float
    price_usd: float
    liquidity_usd: float
    snapshot_ts: datetime
    symbol: str = ""
    token_id: int | None = None
    pair_id: int | None = None
    token_address: str = ""
    pct_m5: float = 0.0
    buy_tax_pct: float | None = 0.0
    sell_tax_pct: float | None = 0.0
    buy_tax_known: bool = True
    sell_tax_known: bool = True
    recent_prices: list[float] = field(default_factory=list)
    security_status: str = SecurityStatus.PASS.value
    require_known_taxes: bool = True


@dataclass(slots=True)
class Quote:
    request: QuoteRequest
    impact_pct: float
    slippage_pct: float
    age_seconds: float
    reject_code: str | None = None
    reject_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.reject_code is None

    @property
    def network_fee_usd(self) -> float:
        return buy_fees(self.request.chain, self.request.notional_usd, self.request.buy_tax_pct).network_usd

    @property
    def dex_fee_usd(self) -> float:
        return buy_fees(self.request.chain, self.request.notional_usd, self.request.buy_tax_pct).dex_usd

    @property
    def tax_fee_usd(self) -> float:
        return buy_fees(self.request.chain, self.request.notional_usd, self.request.buy_tax_pct).tax_usd

    def as_dict(self) -> dict[str, float | str | bool | None]:
        return {
            "impact_pct": round(self.impact_pct, 6),
            "slippage_pct": round(self.slippage_pct, 6),
            "age_seconds": round(self.age_seconds, 2),
            "network_fee_usd": self.network_fee_usd,
            "dex_fee_usd": self.dex_fee_usd,
            "tax_fee_usd": self.tax_fee_usd,
            "reject_code": self.reject_code,
            "reject_reason": self.reject_reason,
            "warnings": self.warnings,
        }


def build_buy_quote(request: QuoteRequest, cfg: StrategyConfig, now: datetime | None = None) -> Quote:
    now = ensure_utc(now) or utc_now()
    snapshot_ts = ensure_utc(request.snapshot_ts) or now
    age = max(0.0, (now - snapshot_ts).total_seconds())
    impact = price_impact_pct(request.notional_usd, request.liquidity_usd)
    slip = slippage_pct(
        impact,
        base_slippage_bps=cfg.max_price_impact_pct * 0 + 50.0,
        pct_m5=request.pct_m5,
    )
    quote = Quote(request=request, impact_pct=impact, slippage_pct=slip, age_seconds=age)

    if request.notional_usd <= 0:
        quote.reject_code, quote.reject_reason = "INVALID_NOTIONAL", "Order size must be positive."
        return quote

    if age > cfg.max_price_age_seconds:
        quote.reject_code = "STALE_DATA"
        quote.reject_reason = f"Market data is {age:.0f}s old (limit {cfg.max_price_age_seconds}s)."
        return quote

    if request.price_usd <= 0:
        quote.reject_code = "STALE_DATA"
        quote.reject_reason = "No usable market price is available."
        return quote

    if request.liquidity_usd < MIN_LIQUIDITY_USD:
        quote.reject_code = "THIN_LIQUIDITY"
        quote.reject_reason = f"Liquidity ${request.liquidity_usd:,.0f} is too thin to simulate a fill."
        return quote

    if request.recent_prices:
        reference = median(request.recent_prices[-3:])
        if reference > 0:
            deviation = abs(request.price_usd - reference) / reference * 100.0
            if deviation > MAX_PRICE_DEVIATION_PCT:
                quote.reject_code = "STALE_DATA"
                quote.reject_reason = (
                    f"Price deviates {deviation:.1f}% from the recent median; refusing a simulated fill."
                )
                return quote

    if impact > cfg.max_price_impact_pct:
        quote.reject_code = "IMPACT_LIMIT"
        quote.reject_reason = (
            f"Estimated price impact {impact:.2f}% exceeds the {cfg.max_price_impact_pct:.2f}% limit."
        )
        return quote

    if request.security_status == SecurityStatus.FAIL.value:
        quote.reject_code = "SECURITY_REJECTED"
        quote.reject_reason = "Security checks failed for this token."
        return quote

    if request.require_known_taxes and not (request.buy_tax_known and request.sell_tax_known):
        quote.reject_code = "SECURITY_INCOMPLETE"
        quote.reject_reason = "Buy/sell taxes are unknown; automatic entry is blocked."
        return quote

    if not request.buy_tax_known or not request.sell_tax_known:
        quote.warnings.append("Token tax is unknown and assumed to be 0%.")
    if request.security_status in {SecurityStatus.WARNING.value, SecurityStatus.UNKNOWN.value}:
        quote.warnings.append(f"Security status is {request.security_status}.")

    return quote

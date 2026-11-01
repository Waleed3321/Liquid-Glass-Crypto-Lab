"""Merge provider security payloads and apply the conservative decision matrix.

Missing information is never treated as safe: a critical field that no provider
reported keeps the token ineligible for automatic entry. Every verdict carries
human-readable reasons and the provider/value behind each field.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.models.enums import Chain, SecurityStatus
from app.providers.base import SecurityField, SecurityResult
from app.providers.registry import Providers

logger = get_logger(__name__)

PASS = SecurityStatus.PASS.value
WARNING = SecurityStatus.WARNING.value
FAIL = SecurityStatus.FAIL.value
UNKNOWN = SecurityStatus.UNKNOWN.value
UNAVAILABLE = SecurityStatus.UNAVAILABLE.value

_SEVERITY = {FAIL: 5, WARNING: 4, PASS: 3, UNKNOWN: 2, UNAVAILABLE: 1}

CRITICAL_FIELDS: dict[str, tuple[str, ...]] = {
    Chain.SOLANA.value: ("honeypot", "mintable", "freezable", "lp_lock", "buy_tax", "sell_tax"),
    Chain.BSC.value: ("honeypot", "buy_tax", "sell_tax", "ownership", "lp_lock"),
}

_MIN_LP_LOCK_PCT = 10.0
_MAX_TOP10_PCT = 60.0
_MAX_TAX_PCT = 10.0

_BASE_RISK = {PASS: 12.0, WARNING: 45.0, UNKNOWN: 65.0, UNAVAILABLE: 80.0, FAIL: 95.0}


@dataclass(slots=True)
class SecurityAssessment:
    chain: str
    token_address: str
    overall: str
    eligible: bool
    critical_pass: int
    critical_total: int
    warning_count: int
    critical_unknown: int
    risk_score: float
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    providers: dict[str, bool] = field(default_factory=dict)
    buy_tax_pct: float | None = 0.0
    sell_tax_pct: float | None = 0.0
    buy_tax_known: bool = False
    sell_tax_known: bool = False
    holder_concentration: float | None = None
    holder_count: int | None = None
    lp_lock_pct: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_notification_fields(self) -> list[tuple[str, str]]:
        return [
            ("Chain", Chain(self.chain).label),
            ("Security", self.overall),
            ("Risk score", f"{self.risk_score:.0f}/100"),
            ("Critical checks", f"{self.critical_pass}/{self.critical_total}"),
        ]

    def summary(self) -> str:
        if not self.reasons:
            return f"Security {self.overall}"
        return f"Security {self.overall}: " + "; ".join(self.reasons[:3])


def _pick(a: SecurityField | None, b: SecurityField | None) -> SecurityField | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if _SEVERITY.get(a.status, 0) >= _SEVERITY.get(b.status, 0) else b


def merge_fields(results: list[SecurityResult]) -> dict[str, SecurityField]:
    merged: dict[str, SecurityField] = {}
    for result in results:
        for name, item in result.fields.items():
            merged[name] = _pick(merged.get(name), item)  # type: ignore[assignment]
    return merged


def _synthesise_chain_taxes(
    chain: str, merged: dict[str, SecurityField], goplus_available: bool
) -> None:
    """Solana has no arbitrary buy/sell tax; its transfer fee is the closest signal."""
    if chain != Chain.SOLANA.value:
        return
    transfer = merged.get("transfer_fee")
    if transfer is not None and transfer.status == FAIL:
        merged["buy_tax"] = SecurityField("buy_tax", FAIL, transfer.value, transfer.reason, transfer.source)
        merged["sell_tax"] = SecurityField("sell_tax", FAIL, transfer.value, transfer.reason, transfer.source)
        return
    if not goplus_available:
        return
    value = float(transfer.value) if transfer and transfer.value is not None else 0.0
    status = transfer.status if transfer is not None else PASS
    reason = transfer.reason if transfer is not None else "No transfer fee reported"
    merged["buy_tax"] = SecurityField("buy_tax", status, 0.0, "Solana tokens have no buy tax", "goplus")
    merged["sell_tax"] = SecurityField("sell_tax", status, value, reason, "goplus")


def _numeric_field(merged: dict[str, SecurityField], name: str) -> float | None:
    item = merged.get(name)
    if item is None or item.status in {UNKNOWN, UNAVAILABLE} or item.value is None:
        return None
    try:
        return float(item.value)
    except (TypeError, ValueError):
        return None


def assess(
    *,
    chain: str,
    token_address: str,
    results: list[SecurityResult],
) -> SecurityAssessment:
    merged = merge_fields(results)
    availability = {r.provider: r.available for r in results}
    goplus_available = any(r.provider == "goplus" and r.available for r in results)
    rugcheck_available = any(r.provider == "rugcheck" and r.available for r in results)
    _synthesise_chain_taxes(chain, merged, goplus_available)

    if not results or not any(availability.values()):
        return SecurityAssessment(
            chain=chain,
            token_address=token_address,
            overall=UNAVAILABLE,
            eligible=False,
            critical_pass=0,
            critical_total=len(CRITICAL_FIELDS.get(chain, ())),
            warning_count=0,
            critical_unknown=len(CRITICAL_FIELDS.get(chain, ())),
            risk_score=90.0,
            fields={},
            reasons=["No security provider returned data; automatic entry is blocked."],
            providers=availability,
            buy_tax_known=False,
            sell_tax_known=False,
        )

    reasons: list[str] = []
    for result in results:
        if not result.available:
            reasons.extend(f"{result.provider}: {r}" for r in result.reasons[:2])

    for name, item in merged.items():
        if item.status in {FAIL, WARNING}:
            reasons.append(f"{name.replace('_', ' ')}: {item.reason}")

    # Direct threshold enforcement independent of provider ratings.
    lp_lock = _numeric_field(merged, "lp_lock")
    if lp_lock is not None and lp_lock < _MIN_LP_LOCK_PCT:
        merged["lp_lock"] = SecurityField(
            "lp_lock", FAIL, lp_lock, f"Only {lp_lock:.1f}% of liquidity is locked or burned", "combined"
        )
        reasons.append(f"lp lock: only {lp_lock:.1f}% of liquidity is locked or burned")
    top10 = _numeric_field(merged, "holder_concentration")
    if top10 is not None and top10 > _MAX_TOP10_PCT:
        merged["holder_concentration"] = SecurityField(
            "holder_concentration", FAIL, top10, f"Top 10 holders control {top10:.1f}% of supply", "combined"
        )
        reasons.append(f"holder concentration: top 10 holders control {top10:.1f}% of supply")

    critical_names = CRITICAL_FIELDS.get(chain, ())
    critical_pass = 0
    critical_unknown = 0
    for name in critical_names:
        item = merged.get(name)
        if item is None or item.status in {UNKNOWN, UNAVAILABLE}:
            critical_unknown += 1
            label = name.replace("_", " ")
            reasons.append(f"{label}: no verified data available (treated as unsafe)")
        elif item.status == PASS:
            critical_pass += 1

    fails = [i for i in merged.values() if i.status == FAIL]
    warnings = [i for i in merged.values() if i.status == WARNING]

    if fails:
        overall = FAIL
    elif critical_unknown:
        overall = UNKNOWN
    elif warnings:
        overall = WARNING
    else:
        overall = PASS

    eligible = overall == PASS or (overall == WARNING and len(warnings) == 1)

    risk = _BASE_RISK.get(overall, 70.0)
    risk += min(15.0, len(warnings) * 5.0)
    risk += min(20.0, critical_unknown * 10.0)
    if top10 is not None:
        risk += max(0.0, top10 - 30.0) * 0.3
    risk = round(min(100.0, max(0.0, risk)), 2)

    if not reasons:
        reasons.append("All checked security fields passed.")

    buy_tax_field = merged.get("buy_tax")
    sell_tax_field = merged.get("sell_tax")
    buy_known = buy_tax_field is not None and buy_tax_field.status not in {UNKNOWN, UNAVAILABLE}
    sell_known = sell_tax_field is not None and sell_tax_field.status not in {UNKNOWN, UNAVAILABLE}
    buy_tax = _numeric_field(merged, "buy_tax") if buy_known else None
    sell_tax = _numeric_field(merged, "sell_tax") if sell_known else None

    holder_count_raw = merged.get("holder_count")
    holder_count = None
    if holder_count_raw is not None and holder_count_raw.value is not None:
        try:
            holder_count = int(float(holder_count_raw.value))
        except (TypeError, ValueError):
            holder_count = None

    return SecurityAssessment(
        chain=chain,
        token_address=token_address,
        overall=overall,
        eligible=eligible,
        critical_pass=critical_pass,
        critical_total=len(critical_names),
        warning_count=len(warnings),
        critical_unknown=critical_unknown,
        risk_score=risk,
        fields={name: item.as_dict() for name, item in merged.items()},
        reasons=reasons,
        providers=availability,
        buy_tax_pct=buy_tax if buy_tax is not None else (0.0 if buy_known else None),
        sell_tax_pct=sell_tax if sell_tax is not None else (0.0 if sell_known else None),
        buy_tax_known=buy_known,
        sell_tax_known=sell_known,
        holder_concentration=top10,
        holder_count=holder_count,
        lp_lock_pct=lp_lock,
        raw={
            "providers": availability,
            "goplus_available": goplus_available,
            "rugcheck_available": rugcheck_available,
        },
    )


def assessment_from_check(check: Any) -> SecurityAssessment:
    """Rebuild a live assessment from the persisted combined security row."""
    fields: dict[str, Any] = check.fields or {}
    chain = getattr(check, "chain", "") or ("bsc" if "ownership" in fields else "solana")
    critical_names = CRITICAL_FIELDS[chain]

    critical_pass = 0
    critical_unknown = 0
    for name in critical_names:
        item = fields.get(name)
        status = (item or {}).get("status")
        if status is None or status in {UNKNOWN, UNAVAILABLE}:
            critical_unknown += 1
        elif status == PASS:
            critical_pass += 1

    warnings = sum(1 for item in fields.values() if (item or {}).get("status") == WARNING)
    overall = check.overall
    eligible = overall == PASS or (overall == WARNING and warnings <= 1)

    def _value(name: str) -> float | None:
        item = fields.get(name) or {}
        if item.get("status") in {UNKNOWN, UNAVAILABLE, FAIL}:
            return None
        try:
            return float(item.get("value"))
        except (TypeError, ValueError):
            return None

    buy_known = (fields.get("buy_tax") or {}).get("status") not in {None, UNKNOWN, UNAVAILABLE}
    sell_known = (fields.get("sell_tax") or {}).get("status") not in {None, UNKNOWN, UNAVAILABLE}
    top10 = _value("holder_concentration")
    holder_count = _value("holder_count")

    return SecurityAssessment(
        chain=chain,
        token_address="",
        overall=overall,
        eligible=eligible,
        critical_pass=critical_pass,
        critical_total=len(critical_names),
        warning_count=warnings,
        critical_unknown=critical_unknown,
        risk_score=float(check.risk_score or 0.0),
        fields=fields,
        reasons=list(check.reasons or []),
        providers=(check.raw or {}).get("providers", {}),
        buy_tax_pct=_value("buy_tax") or 0.0 if buy_known else None,
        sell_tax_pct=_value("sell_tax") or 0.0 if sell_known else None,
        buy_tax_known=buy_known,
        sell_tax_known=sell_known,
        holder_concentration=top10,
        holder_count=int(holder_count) if holder_count is not None else None,
        lp_lock_pct=_value("lp_lock"),
        raw=check.raw or {},
    )


async def check_token(
    providers: Providers, chain: str, token_address: str
) -> tuple[SecurityAssessment, SecurityResult | None, SecurityResult | None]:
    """Run every applicable provider concurrently; a single failure degrades the verdict."""

    async def run(coro, name: str) -> SecurityResult | None:
        try:
            return await coro
        except (TimeoutError, ProviderError) as exc:
            logger.warning(
                "security_provider_failed", extra={"provider": name, "error": str(exc)}
            )
            return None

    tasks = [run(providers.goplus.check(chain, token_address), "goplus")] if providers.goplus else []
    if chain == Chain.SOLANA.value and providers.rugcheck:
        tasks.append(run(providers.rugcheck.check(chain, token_address), "rugcheck"))
    results = await asyncio.gather(*tasks) if tasks else []

    combined = [r for r in results if r is not None]
    assessment = assess(chain=chain, token_address=token_address, results=combined)
    goplus = next((r for r in combined if r.provider == "goplus"), None)
    rugcheck = next((r for r in combined if r.provider == "rugcheck"), None)
    return assessment, goplus, rugcheck

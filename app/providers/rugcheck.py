"""RugCheck adapter (Solana only, keyless)."""

from __future__ import annotations

import logging
from typing import Any

from app.core.errors import ProviderError
from app.models.enums import SecurityStatus
from app.providers.base import SecurityField, SecurityResult, to_float, to_int
from app.providers.cache import AsyncTTLCache
from app.providers.http import ProviderHTTP

logger = logging.getLogger(__name__)

PASS = SecurityStatus.PASS.value
WARN = SecurityStatus.WARNING.value
FAIL = SecurityStatus.FAIL.value
UNKNOWN = SecurityStatus.UNKNOWN.value

DANGER_RISK_NAMES = {
    "honeypot",
    "freeze authority still enabled",
    "mint authority still enabled",
    "low liquidity",
    "single holder ownership",
    "top 10 holders high ownership",
}


class RugCheckProvider:
    def __init__(self, http: ProviderHTTP, cache: AsyncTTLCache, ttl_seconds: int = 300) -> None:
        self.http = http
        self.cache = cache
        self.ttl = ttl_seconds

    async def check(self, chain: str, token_address: str) -> SecurityResult:
        if chain != "solana":
            return SecurityResult(
                chain=chain,
                token_address=token_address,
                provider="rugcheck",
                available=False,
                reasons=["RugCheck only supports Solana"],
            )
        payload = await self.cache.get_or_set(
            f"rugcheck:{token_address}", self.ttl, lambda: self._fetch(token_address)
        )
        if not payload:
            return SecurityResult(
                chain=chain,
                token_address=token_address,
                provider="rugcheck",
                available=False,
                reasons=["RugCheck returned no report"],
            )
        return self._parse(token_address, payload)

    async def _fetch(self, token_address: str) -> dict[str, Any] | None:
        try:
            return await self.http.get_json(f"/tokens/{token_address}/report")
        except ProviderError as exc:
            if exc.details.get("status") in {400, 404}:
                return None
            raise

    def _parse(self, token_address: str, raw: dict[str, Any]) -> SecurityResult:
        fields: dict[str, SecurityField] = {}
        reasons: list[str] = []

        risks = raw.get("risks") or []
        danger = [r for r in risks if str(r.get("level")).lower() in {"danger", "critical"}]
        warnings = [r for r in risks if str(r.get("level")).lower() in {"warn", "warning"}]
        for risk in risks:
            reasons.append(str(risk.get("description") or risk.get("name") or "RugCheck risk"))

        risk_score = to_int(raw.get("score_normalised"), -1)
        if risk_score >= 0:
            if risk_score >= 60:
                status = FAIL
            elif risk_score >= 35:
                status = WARN
            else:
                status = PASS
            fields["rugcheck_risk"] = SecurityField(
                "rugcheck_risk", status, risk_score, f"RugCheck risk score {risk_score}", "rugcheck"
            )

        if raw.get("rugged") is True:
            fields["rugged"] = SecurityField(
                "rugged", FAIL, True, "RugCheck marks this token as rugged", "rugcheck"
            )

        markets = raw.get("markets") or []
        lp_locked = None
        for market in markets:
            lp = market.get("lp") or {}
            if lp.get("lpLockedPct") is not None:
                lp_locked = to_float(lp.get("lpLockedPct"))
                break
        if lp_locked is not None:
            if lp_locked >= 50:
                status, reason = PASS, f"{lp_locked:.1f}% of LP is locked or burned"
            elif lp_locked >= 10:
                status, reason = WARN, f"Only {lp_locked:.1f}% of LP is locked or burned"
            else:
                status, reason = FAIL, f"LP is effectively unlocked ({lp_locked:.1f}% locked)"
            fields["lp_lock"] = SecurityField("lp_lock", status, lp_locked, reason, "rugcheck")

        top_holders = raw.get("topHolders") or []
        if top_holders:
            percents = sorted(
                (to_float(h.get("pct")) for h in top_holders[:10]), reverse=True
            )
            top10 = round(sum(percents), 3)
            if top10 > 60:
                status, reason = FAIL, f"Top 10 holders control {top10:.1f}% of supply"
            elif top10 >= 45:
                status, reason = WARN, f"Top 10 holders control {top10:.1f}% of supply"
            else:
                status, reason = PASS, f"Top 10 holders control {top10:.1f}% of supply"
            fields["holder_concentration"] = SecurityField(
                "holder_concentration", status, top10, reason, "rugcheck"
            )

        total_holders = to_int(raw.get("totalHolders"), -1)
        if total_holders >= 0:
            fields["holder_count"] = SecurityField(
                "holder_count",
                PASS if total_holders >= 100 else WARN,
                total_holders,
                f"{total_holders} holders",
                "rugcheck",
            )

        for name, label in (("mintAuthority", "Mint authority"), ("freezeAuthority", "Freeze authority")):
            value = raw.get(name)
            if value:
                fields["mint_authority" if name == "mintAuthority" else "freeze_authority"] = SecurityField(
                    "mint_authority" if name == "mintAuthority" else "freeze_authority",
                    FAIL,
                    value,
                    f"{label} is still active",
                    "rugcheck",
                )

        if danger:
            reasons.append("RugCheck flagged danger-level risks")
        if warnings:
            reasons.append("RugCheck flagged warnings")

        return SecurityResult(
            chain="solana",
            token_address=token_address,
            provider="rugcheck",
            fields=fields,
            reasons=reasons,
            raw=raw,
            available=True,
        )

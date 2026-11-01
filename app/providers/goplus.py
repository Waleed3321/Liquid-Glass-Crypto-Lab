"""GoPlus token-security adapter (keyless) for BNB Chain and Solana."""

from __future__ import annotations

import logging
from typing import Any

from app.models.enums import Chain, SecurityStatus
from app.providers.base import SecurityField, SecurityResult, to_float, to_int
from app.providers.cache import AsyncTTLCache
from app.providers.http import ProviderHTTP

logger = logging.getLogger(__name__)

ZERO_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "0x0000000000000000000000000000000000000001",
}

PASS = SecurityStatus.PASS.value
WARN = SecurityStatus.WARNING.value
FAIL = SecurityStatus.FAIL.value
UNKNOWN = SecurityStatus.UNKNOWN.value
UNAVAILABLE = SecurityStatus.UNAVAILABLE.value


def _flag_field(name: str, raw_value: Any, *, fail_value: str = "1", source: str = "goplus") -> SecurityField:
    if raw_value is None:
        return SecurityField(name, UNKNOWN, None, "Provider did not return this field", source)
    text = str(raw_value).strip().lower()
    if text in {"1", "true", "yes"}:
        return SecurityField(name, FAIL, True, f"{name.replace('_', ' ')} flag is set", source)
    if text in {"0", "false", "no"}:
        return SecurityField(name, PASS, False, f"{name.replace('_', ' ')} flag is clear", source)
    return SecurityField(name, UNKNOWN, raw_value, "Unrecognised provider value", source)


def _tax_field(name: str, raw_value: Any) -> SecurityField:
    if raw_value in (None, "", "-1"):
        return SecurityField(name, UNKNOWN, None, "Tax not reported by provider", "goplus")
    value = to_float(raw_value, -1)
    if value < 0:
        return SecurityField(name, UNKNOWN, raw_value, "Tax unavailable", "goplus")
    pct = value * 100 if value <= 1 else value
    if pct > 10:
        return SecurityField(name, FAIL, round(pct, 4), f"{name.replace('_', ' ')} {pct:.2f}% exceeds 10%", "goplus")
    if pct > 5:
        return SecurityField(name, WARN, round(pct, 4), f"{name.replace('_', ' ')} {pct:.2f}% is elevated", "goplus")
    return SecurityField(name, PASS, round(pct, 4), f"{name.replace('_', ' ')} {pct:.2f}%", "goplus")


class GoPlusProvider:
    def __init__(self, http: ProviderHTTP, cache: AsyncTTLCache, ttl_seconds: int = 600) -> None:
        self.http = http
        self.cache = cache
        self.ttl = ttl_seconds

    async def check(self, chain: str, token_address: str) -> SecurityResult:
        cache_key = f"goplus:{chain}:{token_address.lower()}"
        payload = await self.cache.get_or_set(
            cache_key, self.ttl, lambda: self._fetch(chain, token_address)
        )
        if not payload:
            return SecurityResult(
                chain=chain,
                token_address=token_address,
                provider="goplus",
                fields={},
                reasons=["GoPlus returned no security data"],
                raw={},
                available=False,
            )
        return self._parse(chain, token_address, payload)

    async def _fetch(self, chain: str, token_address: str) -> dict[str, Any] | None:
        if chain == Chain.BSC.value:
            data = await self.http.get_json(
                "/token_security/56", params={"contract_addresses": token_address.lower()}
            )
            key = token_address.lower()
        elif chain == Chain.SOLANA.value:
            data = await self.http.get_json(
                "/solana/token_security", params={"contract_addresses": token_address}
            )
            key = token_address
        else:
            return None
        result = (data or {}).get("result") or {}
        if key not in result and result:
            key = next(iter(result))
        return result.get(key)

    def _parse(self, chain: str, token_address: str, raw: dict[str, Any]) -> SecurityResult:
        if chain == Chain.BSC.value:
            fields = self._parse_bsc(raw)
        else:
            fields = self._parse_solana(raw)
        reasons = [f.reason for f in fields.values() if f.status in {FAIL, WARN}]
        return SecurityResult(
            chain=chain,
            token_address=token_address,
            provider="goplus",
            fields=fields,
            reasons=reasons,
            raw=raw,
        )

    # -- BNB Chain ---------------------------------------------------------
    def _parse_bsc(self, raw: dict[str, Any]) -> dict[str, SecurityField]:
        fields: dict[str, SecurityField] = {}
        fields["honeypot"] = _flag_field("honeypot", raw.get("is_honeypot"))

        cannot_sell = raw.get("cannot_sell_all")
        if cannot_sell is not None:
            fields["sell_restriction"] = _flag_field("sell_restriction", cannot_sell)

        fields["buy_tax"] = _tax_field("buy_tax", raw.get("buy_tax"))
        fields["sell_tax"] = _tax_field("sell_tax", raw.get("sell_tax"))
        fields["mintable"] = _flag_field("mintable", raw.get("is_mintable"))
        fields["pausable"] = _flag_field("pausable", raw.get("transfer_pausable"))
        fields["blacklist"] = _flag_field("blacklist", raw.get("is_blacklisted"))
        fields["proxy_contract"] = _flag_field("proxy_contract", raw.get("is_proxy"))

        hidden_owner = str(raw.get("hidden_owner") or "0") == "1"
        take_back = str(raw.get("can_take_back_ownership") or "0") == "1"
        owner = str(raw.get("owner_address") or "").lower()
        renounced = owner in ZERO_ADDRESSES or owner == ""
        if hidden_owner or take_back:
            fields["ownership"] = SecurityField(
                "ownership", FAIL, raw.get("owner_address"), "Owner privileges can be reclaimed", "goplus"
            )
        elif renounced:
            fields["ownership"] = SecurityField(
                "ownership", PASS, raw.get("owner_address"), "Ownership renounced", "goplus"
            )
        else:
            fields["ownership"] = SecurityField(
                "ownership", WARN, raw.get("owner_address"), "Owner can still modify the contract", "goplus"
            )

        open_source = raw.get("is_open_source")
        if open_source is not None:
            fields["open_source"] = SecurityField(
                "open_source",
                PASS if str(open_source) == "1" else WARN,
                str(open_source) == "1",
                "Contract source is verified" if str(open_source) == "1" else "Contract source is not verified",
                "goplus",
            )

        # LP lock / burn ratio
        lp_holders = raw.get("lp_holders") or []
        locked_pct = 0.0
        lp_seen = False
        for holder in lp_holders:
            lp_seen = True
            address = str(holder.get("address") or "").lower()
            percent = to_float(holder.get("percent"))
            percent_pct = percent * 100 if percent <= 1 else percent
            if str(holder.get("is_locked")) == "1" or address in ZERO_ADDRESSES:
                locked_pct += percent_pct
        if lp_seen:
            locked_pct = min(100.0, round(locked_pct, 3))
            if locked_pct >= 50:
                status, reason = PASS, f"{locked_pct:.1f}% of LP is locked or burned"
            elif locked_pct >= 10:
                status, reason = WARN, f"Only {locked_pct:.1f}% of LP is locked or burned"
            else:
                status, reason = FAIL, f"LP is effectively unlocked ({locked_pct:.1f}% locked)"
            fields["lp_lock"] = SecurityField("lp_lock", status, locked_pct, reason, "goplus")

        # Top-10 holder concentration excluding burn / pool addresses
        holders = raw.get("holders") or []
        if holders:
            percents: list[float] = []
            for holder in holders[:20]:
                address = str(holder.get("address") or "").lower()
                if address in ZERO_ADDRESSES:
                    continue
                value = to_float(holder.get("percent"))
                percents.append(value * 100 if value <= 1 else value)
            top10 = round(sum(sorted(percents, reverse=True)[:10]), 3)
            if top10 > 60:
                status, reason = FAIL, f"Top 10 holders control {top10:.1f}% of supply"
            elif top10 >= 45:
                status, reason = WARN, f"Top 10 holders control {top10:.1f}% of supply"
            else:
                status, reason = PASS, f"Top 10 holders control {top10:.1f}% of supply"
            fields["holder_concentration"] = SecurityField(
                "holder_concentration", status, top10, reason, "goplus"
            )

        holder_count = to_int(raw.get("holder_count"), -1)
        if holder_count >= 0:
            fields["holder_count"] = SecurityField(
                "holder_count",
                PASS if holder_count >= 100 else WARN,
                holder_count,
                f"{holder_count} holders",
                "goplus",
            )

        return fields

    # -- Solana ------------------------------------------------------------
    def _parse_solana(self, raw: dict[str, Any]) -> dict[str, SecurityField]:
        fields: dict[str, SecurityField] = {}

        def authority_field(name: str, payload: Any, label: str) -> None:
            if not isinstance(payload, dict):
                fields[name] = SecurityField(name, UNKNOWN, None, f"{label} status unavailable", "goplus")
                return
            active = str(payload.get("status")) == "1"
            authorities = payload.get("authority") or []
            if active and authorities:
                fields[name] = SecurityField(
                    name, FAIL, authorities, f"{label} is still active", "goplus"
                )
            elif active:
                fields[name] = SecurityField(
                    name, WARN, None, f"{label} is reported active without an authority list", "goplus"
                )
            else:
                fields[name] = SecurityField(name, PASS, None, f"{label} is revoked", "goplus")

        authority_field("mintable", raw.get("mintable"), "Mint authority")
        authority_field("freezable", raw.get("freezable"), "Freeze authority")
        authority_field("closable", raw.get("closable"), "Account closing authority")

        mutable = raw.get("metadata_mutable")
        if isinstance(mutable, dict):
            active = str(mutable.get("status")) == "1"
            fields["metadata_mutable"] = SecurityField(
                "metadata_mutable",
                WARN if active else PASS,
                active,
                "Metadata can be changed" if active else "Metadata is immutable",
                "goplus",
            )

        if str(raw.get("non_transferable") or "0") == "1":
            fields["transferable"] = SecurityField(
                "transferable", FAIL, False, "Token is non-transferable", "goplus"
            )

        transfer_fee = raw.get("transfer_fee")
        if isinstance(transfer_fee, dict) and transfer_fee:
            fee_pct = to_float(
                transfer_fee.get("transfer_fee_basis_points") or transfer_fee.get("fee", 0)
            )
            if "transfer_fee_basis_points" in transfer_fee:
                fee_pct = fee_pct / 100.0
            if fee_pct > 10:
                status, reason = FAIL, f"Transfer fee is {fee_pct:.2f}%"
            elif fee_pct > 1:
                status, reason = WARN, f"Transfer fee is {fee_pct:.2f}%"
            else:
                status, reason = PASS, f"Transfer fee is {fee_pct:.2f}%"
            fields["transfer_fee"] = SecurityField("transfer_fee", status, round(fee_pct, 4), reason, "goplus")

        return fields

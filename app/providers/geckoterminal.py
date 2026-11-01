"""GeckoTerminal adapter - primary new-pool discovery source (keyless)."""

from __future__ import annotations

import logging
from typing import Any

from app.core.clock import from_iso_timestamp
from app.providers.base import PoolDiscovery, to_float, to_int
from app.providers.cache import AsyncTTLCache
from app.providers.http import ProviderHTTP

logger = logging.getLogger(__name__)

NETWORK_BY_CHAIN = {"solana": "solana", "bsc": "bsc"}

KNOWN_QUOTE_TOKENS: dict[str, set[str]] = {
    "solana": {
        "so11111111111111111111111111111111111111112",  # SOL
        "epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v",  # USDC
        "es9vmfrzacermjfrf4h2fyd4kconky11mcc8bennynyb",  # USDT
    },
    "bsc": {
        "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
        "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
        "0x55d398326f99059ff775485246999027b3197955",  # USDT
        "0x8ac76a51cc950d9822d68b83fef1e97b32cd580d",  # USDC
        "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82",  # CAKE
    },
}


def _relationship_address(pool: dict[str, Any], key: str) -> str | None:
    data = (pool.get("relationships") or {}).get(key) or {}
    identifier = (data.get("data") or {}).get("id")
    if not identifier or "_" not in identifier:
        return None
    return identifier.split("_", 1)[1]


class GeckoTerminalProvider:
    def __init__(self, http: ProviderHTTP, cache: AsyncTTLCache, ttl_seconds: int = 55) -> None:
        self.http = http
        self.cache = cache
        self.ttl = ttl_seconds

    async def new_pools(self, chain: str, pages: int = 2) -> list[PoolDiscovery]:
        network = NETWORK_BY_CHAIN.get(chain)
        if not network:
            return []
        results: list[PoolDiscovery] = []
        seen: set[str] = set()
        last_error: Exception | None = None
        for page in range(1, max(1, pages) + 1):
            try:
                payload = await self.cache.get_or_set(
                    f"gt:new_pools:{chain}:{page}",
                    self.ttl,
                    lambda page=page: self.http.get_json(
                        f"/networks/{network}/new_pools", params={"page": page}
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - keep earlier pages' results
                last_error = exc
                logger.warning(
                    "geckoterminal_page_failed",
                    extra={"chain": chain, "page": page, "error": str(exc)},
                )
                continue
            for pool in (payload or {}).get("data") or []:
                parsed = self._parse_pool(chain, pool)
                if parsed and parsed.pool_address not in seen:
                    seen.add(parsed.pool_address)
                    results.append(parsed)
        if not results and last_error is not None:
            raise last_error
        return results

    def _parse_pool(self, chain: str, pool: dict[str, Any]) -> PoolDiscovery | None:
        attributes = pool.get("attributes") or {}
        base_address = _relationship_address(pool, "base_token")
        quote_address = _relationship_address(pool, "quote_token")
        if not base_address:
            return None

        known = KNOWN_QUOTE_TOKENS.get(chain, set())
        token_address = base_address
        quote_symbol: str | None = None
        name = str(attributes.get("name") or "")
        parts = [part.strip() for part in name.split("/")]
        base_symbol = parts[0] if parts and parts[0] else ""
        if len(parts) > 1 and parts[1]:
            quote_symbol = parts[1]

        if quote_address and base_address.lower() in known and quote_address.lower() not in known:
            token_address = quote_address
            quote_symbol = base_symbol or None
            base_symbol = parts[1] if len(parts) > 1 else base_symbol

        if not base_symbol:
            base_symbol = token_address[:6]

        created = from_iso_timestamp(attributes.get("pool_created_at"))
        price = to_float(attributes.get("base_token_price_usd"))
        if token_address != base_address:
            price = to_float(attributes.get("quote_token_price_usd"))

        volume_raw = attributes.get("volume_usd") or {}
        txns_raw = attributes.get("transactions") or {}
        changes_raw = attributes.get("price_change_percentage") or {}

        volume = {
            window: to_float(volume_raw.get(window))
            for window in ("m5", "m15", "m30", "h1", "h6", "h24")
        }
        txns = {
            window: {
                "buys": to_int((txns_raw.get(window) or {}).get("buys")),
                "sells": to_int((txns_raw.get(window) or {}).get("sells")),
                "buyers": to_int((txns_raw.get(window) or {}).get("buyers")),
                "sellers": to_int((txns_raw.get(window) or {}).get("sellers")),
            }
            for window in ("m5", "m15", "m30", "h1", "h6", "h24")
        }
        price_change = {
            window: to_float(changes_raw.get(window))
            for window in ("m5", "m15", "m30", "h1", "h6", "h24")
        }

        return PoolDiscovery(
            chain=chain,
            token_address=token_address,
            pool_address=str(attributes.get("address") or pool.get("id") or ""),
            symbol=base_symbol[:32],
            name=(parts[0] if parts else base_symbol)[:120],
            dex_id=((pool.get("relationships") or {}).get("dex") or {}).get("data", {}).get("id"),
            quote_symbol=quote_symbol,
            created_at=created,
            price_usd=price,
            liquidity_usd=to_float(attributes.get("reserve_in_usd")),
            market_cap_usd=to_float(attributes.get("market_cap_usd")),
            fdv_usd=to_float(attributes.get("fdv_usd")),
            volume=volume,
            txns=txns,
            price_change=price_change,
            raw=pool,
        )

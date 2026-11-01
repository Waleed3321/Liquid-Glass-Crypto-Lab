"""DEX Screener adapter - market data enrichment (keyless, 60 req/min)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.clock import from_iso_timestamp
from app.providers.base import MarketQuote, PoolDiscovery, to_float, to_int
from app.providers.cache import AsyncTTLCache
from app.providers.http import ProviderHTTP

logger = logging.getLogger(__name__)

MAX_ADDRESSES_PER_CALL = 30


def _txns(raw: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {
        window: {
            "buys": to_int((raw.get(window) or {}).get("buys")),
            "sells": to_int((raw.get(window) or {}).get("sells")),
        }
        for window in ("m5", "m15", "m30", "h1", "h6", "h24")
    }


class DexScreenerProvider:
    def __init__(self, http: ProviderHTTP, cache: AsyncTTLCache, ttl_seconds: int = 40) -> None:
        self.http = http
        self.cache = cache
        self.ttl = ttl_seconds

    async def quotes(self, addresses: list[str]) -> list[MarketQuote]:
        unique = [address for address in dict.fromkeys(a for a in addresses if a)]
        quotes: list[MarketQuote] = []
        for start in range(0, len(unique), MAX_ADDRESSES_PER_CALL):
            chunk = unique[start : start + MAX_ADDRESSES_PER_CALL]
            if not chunk:
                continue
            joined = ",".join(chunk)
            payload = await self.cache.get_or_set(
                f"ds:tokens:{joined}",
                self.ttl,
                lambda joined=joined: self.http.get_json(f"/latest/dex/tokens/{joined}"),
            )
            for pair in (payload or {}).get("pairs") or []:
                quote = self._parse_pair(pair)
                if quote:
                    quotes.append(quote)
        return quotes

    async def new_pools(
        self, chain: str, *, limit: int = 20, window_start: datetime | None = None
    ) -> list[PoolDiscovery]:
        """Fallback discovery from the latest token profiles.

        GeckoTerminal rate-limits whole shared egress IPs (Render's included), so
        a chain's primary discovery can fail for minutes. DEX Screener publishes
        the newest token profiles, which we hydrate into pairs with ``quotes``.
        """
        profiles = await self.cache.get_or_set(
            "ds:token-profiles",
            self.ttl,
            lambda: self.http.get_json("/token-profiles/latest/v1"),
        )
        addresses: list[str] = []
        for item in profiles or []:
            if str(item.get("chainId") or "") != chain:
                continue
            address = item.get("tokenAddress")
            if address and address not in addresses:
                addresses.append(str(address))
            if len(addresses) >= limit:
                break
        if not addresses:
            return []

        pools: list[PoolDiscovery] = []
        for quote in await self.quotes(addresses):
            if quote.chain != chain or not quote.pool_address:
                continue
            if quote.created_at is None:
                continue
            if window_start is not None and quote.created_at < window_start:
                continue
            pools.append(
                PoolDiscovery(
                    chain=quote.chain,
                    token_address=quote.token_address,
                    pool_address=quote.pool_address,
                    symbol=quote.symbol,
                    name=quote.name,
                    dex_id=quote.dex_id,
                    quote_symbol=quote.quote_symbol,
                    created_at=quote.created_at,
                    price_usd=quote.price_usd,
                    liquidity_usd=quote.liquidity_usd,
                    market_cap_usd=quote.market_cap_usd,
                    fdv_usd=quote.fdv_usd,
                    volume=dict(quote.volume),
                    txns={window: dict(values) for window, values in quote.txns.items()},
                    price_change=dict(quote.price_change),
                    raw=dict(quote.raw),
                    source="dexscreener",
                )
            )
        return pools

    async def search(self, query: str) -> list[MarketQuote]:
        payload = await self.cache.get_or_set(
            f"ds:search:{query.lower()}",
            self.ttl,
            lambda: self.http.get_json("/latest/dex/search", params={"q": query}),
        )
        return [quote for pair in (payload or {}).get("pairs") or [] if (quote := self._parse_pair(pair))]

    def _parse_pair(self, pair: dict[str, Any]) -> MarketQuote | None:
        base = pair.get("baseToken") or {}
        quote = pair.get("quoteToken") or {}
        address = base.get("address")
        chain = pair.get("chainId")
        if not address or chain not in {"solana", "bsc"}:
            return None

        info = pair.get("info") or {}
        websites = info.get("websites") or []
        volume_raw = pair.get("volume") or {}
        change_raw = pair.get("priceChange") or {}
        liquidity = pair.get("liquidity") or {}

        return MarketQuote(
            chain=chain,
            token_address=address,
            pool_address=str(pair.get("pairAddress") or ""),
            symbol=str(base.get("symbol") or "")[:32],
            name=str(base.get("name") or "")[:120],
            dex_id=pair.get("dexId"),
            quote_symbol=quote.get("symbol"),
            price_usd=to_float(pair.get("priceUsd")),
            liquidity_usd=to_float(liquidity.get("usd")),
            market_cap_usd=to_float(pair.get("marketCap")),
            fdv_usd=to_float(pair.get("fdv")),
            volume={
                window: to_float(volume_raw.get(window))
                for window in ("m5", "m15", "m30", "h1", "h6", "h24")
            },
            txns=_txns(pair.get("txns") or {}),
            price_change={
                window: to_float(change_raw.get(window))
                for window in ("m5", "m15", "m30", "h1", "h6", "h24")
            },
            created_at=from_iso_timestamp(pair.get("pairCreatedAt")),
            image_url=info.get("imageUrl"),
            website_url=websites[0].get("url") if websites else None,
            raw=pair,
        )

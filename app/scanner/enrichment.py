"""Enrichment stage: attach DEX Screener market data to candidate tokens."""

from __future__ import annotations

from app.core.logging import get_logger
from app.providers.base import MarketQuote
from app.providers.registry import Providers

logger = get_logger(__name__)


async def enrich_quotes(
    providers: Providers,
    addresses: list[str],
    *,
    batch_size: int = 25,
    max_batches: int = 2,
) -> tuple[dict[str, list[MarketQuote]], list[str]]:
    if providers.dexscreener is None or not addresses:
        return {}, []

    unique = list(dict.fromkeys(address for address in addresses if address))
    batches = [
        unique[start : start + batch_size]
        for start in range(0, min(len(unique), batch_size * max_batches), batch_size)
    ]
    by_address: dict[str, list[MarketQuote]] = {}
    errors: list[str] = []
    for batch in batches:
        try:
            quotes = await providers.dexscreener.quotes(batch)
        except Exception as exc:
            logger.warning("enrichment_failed", extra={"error": str(exc)})
            errors.append(str(exc))
            continue
        for quote in quotes:
            by_address.setdefault(quote.token_address.lower(), []).append(quote)
    return by_address, errors

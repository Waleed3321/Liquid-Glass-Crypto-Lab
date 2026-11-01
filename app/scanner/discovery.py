"""Discovery stage: new pools on Solana and BNB Chain inside the 6h window."""

from __future__ import annotations

from datetime import datetime

from app.core.logging import get_logger
from app.providers.base import PoolDiscovery
from app.providers.registry import Providers

logger = get_logger(__name__)

CHAINS = ("solana", "bsc")


async def discover_new_pools(
    providers: Providers, *, window_start: datetime, pages: int = 2
) -> tuple[list[PoolDiscovery], list[str]]:
    """Return pools created inside the window plus provider error messages."""
    results: list[PoolDiscovery] = []
    errors: list[str] = []
    if providers.geckoterminal is None:
        return results, ["GeckoTerminal provider is not configured"]

    for chain in CHAINS:
        try:
            pools = await providers.geckoterminal.new_pools(chain, pages=pages)
        except Exception as exc:  # provider failure must not abort the tick
            logger.warning("discovery_failed", extra={"chain": chain, "error": str(exc)})
            errors.append(f"{chain}: {exc}")
            continue

        seen: set[str] = set()
        for pool in pools:
            if not pool.pool_address or not pool.token_address:
                continue
            if pool.created_at is None or pool.created_at < window_start:
                continue
            key = f"{pool.chain}:{pool.pool_address}"
            if key in seen:
                continue
            seen.add(key)
            results.append(pool)
    return results, errors

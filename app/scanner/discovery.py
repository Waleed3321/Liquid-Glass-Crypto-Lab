"""Discovery stage: new pools on Solana and BNB Chain inside the 6h window."""

from __future__ import annotations

from datetime import datetime

from app.core.logging import get_logger
from app.providers.base import PoolDiscovery
from app.providers.registry import Providers

logger = get_logger(__name__)

CHAINS = ("solana", "bsc")


def _in_window(pools: list[PoolDiscovery], window_start: datetime) -> list[PoolDiscovery]:
    seen: set[str] = set()
    inside: list[PoolDiscovery] = []
    for pool in pools:
        if not pool.pool_address or not pool.token_address:
            continue
        if pool.created_at is None or pool.created_at < window_start:
            continue
        key = f"{pool.chain}:{pool.pool_address}"
        if key in seen:
            continue
        seen.add(key)
        inside.append(pool)
    return inside


async def discover_new_pools(
    providers: Providers, *, window_start: datetime, pages: int = 1
) -> tuple[list[PoolDiscovery], list[str]]:
    """Return pools created inside the window plus provider error messages.

    GeckoTerminal is primary. When it is unavailable or returns nothing for a
    chain (it rate-limits shared egress IPs), DEX Screener's newest profiles are
    used as a fallback so both chains keep discovering new coins.
    """
    results: list[PoolDiscovery] = []
    errors: list[str] = []

    for chain in CHAINS:
        pools: list[PoolDiscovery] = []
        if providers.geckoterminal is not None:
            try:
                pools = await providers.geckoterminal.new_pools(chain, pages=pages)
            except Exception as exc:  # provider failure must not abort the tick
                logger.warning("discovery_failed", extra={"chain": chain, "error": str(exc)})
                errors.append(f"{chain}: {exc}")
        else:
            errors.append("GeckoTerminal provider is not configured")

        inside = _in_window(pools, window_start)
        if not inside and providers.dexscreener is not None:
            try:
                fallback = await providers.dexscreener.new_pools(
                    chain, window_start=window_start
                )
                inside = _in_window(fallback, window_start)
                if inside:
                    logger.info(
                        "discovery_fallback_used",
                        extra={"chain": chain, "pools": len(inside)},
                    )
            except Exception as exc:  # noqa: BLE001 - fallback is best effort
                logger.warning(
                    "discovery_fallback_failed", extra={"chain": chain, "error": str(exc)}
                )
                errors.append(f"{chain}: dexscreener {exc}")

        results.extend(inside)
    return results, errors

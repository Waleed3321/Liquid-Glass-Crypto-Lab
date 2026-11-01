"""Builds and owns every provider adapter for one application process."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.providers.cache import AsyncTTLCache
from app.providers.dexscreener import DexScreenerProvider
from app.providers.discord import DiscordNotifier
from app.providers.geckoterminal import GeckoTerminalProvider
from app.providers.goplus import GoPlusProvider
from app.providers.http import ProviderHTTP
from app.providers.rate_limit import TokenBucket
from app.providers.rugcheck import RugCheckProvider


@dataclass
class Providers:
    http: dict[str, ProviderHTTP] = field(default_factory=dict)
    cache: AsyncTTLCache = field(default_factory=AsyncTTLCache)
    geckoterminal: GeckoTerminalProvider | None = None
    dexscreener: DexScreenerProvider | None = None
    goplus: GoPlusProvider | None = None
    rugcheck: RugCheckProvider | None = None
    discord: DiscordNotifier | None = None

    def health(self) -> dict[str, object]:
        return {
            name: client.health() for name, client in self.http.items()
        } | {
            "cache": self.cache.stats(),
            "discord": {
                "configured": bool(self.discord and self.discord.configured),
                "mode": self.discord.mode if self.discord else "disabled",
            },
        }

    async def close(self) -> None:
        for client in self.http.values():
            await client.close()
        if self.discord:
            await self.discord.close()


def build_providers(client: httpx.AsyncClient | None = None) -> Providers:
    providers = Providers()
    limits = settings.provider_rate_limits()
    ttls = settings.provider_cache_ttls()

    shared_client = client

    def make(name: str, base_url: str) -> ProviderHTTP:
        http = ProviderHTTP(
            name,
            base_url,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            limiter=TokenBucket(name, limits[name]),
            client=shared_client,
        )
        providers.http[name] = http
        return http

    gt_http = make("geckoterminal", settings.geckoterminal_base_url)
    ds_http = make("dexscreener", settings.dexscreener_base_url)
    goplus_http = make("goplus", settings.goplus_base_url)
    rugcheck_http = make("rugcheck", settings.rugcheck_base_url)

    providers.geckoterminal = GeckoTerminalProvider(
        gt_http, providers.cache, ttl_seconds=ttls["geckoterminal"]
    )
    providers.dexscreener = DexScreenerProvider(
        ds_http, providers.cache, ttl_seconds=ttls["dexscreener"]
    )
    providers.goplus = GoPlusProvider(goplus_http, providers.cache, ttl_seconds=ttls["goplus"])
    providers.rugcheck = RugCheckProvider(
        rugcheck_http, providers.cache, ttl_seconds=ttls["rugcheck"]
    )
    providers.discord = DiscordNotifier(client=shared_client)
    return providers

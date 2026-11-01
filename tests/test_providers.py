"""Provider resilience: rate limits, retries, 429 handling, circuit breaker, cache
and Discord failure isolation."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import ProviderError, RateLimitedError
from app.db.session import session_scope
from app.models import Notification
from app.notifications.dispatcher import NotificationDispatcher
from app.providers.cache import AsyncTTLCache
from app.providers.discord import DiscordNotifier
from app.providers.http import ProviderHTTP
from app.providers.rate_limit import TokenBucket


def _http(handler, **kwargs) -> tuple[ProviderHTTP, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = ProviderHTTP(
        kwargs.pop("name", "fake"),
        "https://fake.test",
        limiter=TokenBucket("fake", 6000),
        client=client,
        **kwargs,
    )
    return http, client


async def test_token_bucket_denies_when_budget_is_exhausted():
    bucket = TokenBucket("test", per_minute=60, capacity=1)
    assert await bucket.acquire() is True
    with pytest.raises(RateLimitedError):
        await bucket.acquire(wait_seconds=0.05)
    assert bucket.snapshot()["denied"] == 1


async def test_429_triggers_one_courtesy_retry_then_rate_limit_error():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "slow down"})

    http, client = _http(handler, max_retries=3)
    with pytest.raises(RateLimitedError) as exc:
        await http.get_json("/pools")
    assert exc.value.code == "RATE_LIMITED"
    assert calls["count"] == 2
    await client.aclose()


async def test_transient_500_is_retried_until_success():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"ok": True})

    http, client = _http(handler, max_retries=2)
    assert await http.get_json("/pools") == {"ok": True}
    assert calls["count"] == 2
    assert http.circuit_open is False
    await client.aclose()


async def test_repeated_failures_open_the_circuit_breaker():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    http, client = _http(handler, max_retries=0, circuit_threshold=2)
    with pytest.raises(ProviderError):
        await http.get_json("/pools")
    with pytest.raises(ProviderError):
        await http.get_json("/pools")
    assert http.circuit_open is True

    with pytest.raises(ProviderError) as exc:
        await http.get_json("/pools")
    assert exc.value.code == "PROVIDER_CIRCUIT_OPEN"
    assert http.health()["consecutive_failures"] == 2
    await client.aclose()


async def test_invalid_json_is_reported_as_provider_error():
    http, client = _http(lambda request: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(ProviderError):
        await http.get_json("/pools")
    await client.aclose()


async def test_ttl_cache_expires_and_deduplicates_work():
    cache = AsyncTTLCache()
    await cache.set("key", {"value": 1}, ttl_seconds=5)
    assert await cache.get("key") == {"value": 1}
    await cache.set("short", 1, ttl_seconds=0.01)
    await asyncio.sleep(0.02)
    assert await cache.get("short") is None

    calls = {"count": 0}

    async def factory() -> str:
        calls["count"] += 1
        return "result"

    assert await cache.get_or_set("computed", 5, factory) == "result"
    assert await cache.get_or_set("computed", 5, factory) == "result"
    assert calls["count"] == 1
    assert cache.stats()["hits"] >= 2


async def test_discord_failure_keeps_notification_pending_for_retry():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
    )
    notifier = DiscordNotifier(webhook_url="https://discord.test/hook", client=client, enabled=True)
    dispatcher = NotificationDispatcher(notifier)

    await dispatcher.queue(kind="TEST", title="Discord outage", message="body")
    assert await dispatcher.dispatch_pending() == 0

    async with session_scope() as session:
        rows = (await session.execute(select(Notification))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "PENDING"
    assert rows[0].attempts == 1
    assert "500" in (rows[0].last_error or "")
    await client.aclose()


async def test_unconfigured_discord_skips_notifications_without_raising():
    notifier = DiscordNotifier(webhook_url="", bot_token="", channel_id="")
    dispatcher = NotificationDispatcher(notifier)
    assert dispatcher.configured is False

    await dispatcher.queue(kind="TEST", title="No webhook", message="body")
    assert await dispatcher.dispatch_pending() == 0

    async with session_scope() as session:
        rows = (await session.execute(select(Notification))).scalars().all()
    assert rows[0].status == "SKIPPED"
    assert "not configured" in (rows[0].last_error or "")


async def test_geckoterminal_keeps_first_page_when_later_page_is_rate_limited():
    from app.providers.geckoterminal import GeckoTerminalProvider

    pool = {
        "id": "solana_pool-one",
        "attributes": {
            "address": "pool-one",
            "name": "TEST / SOL",
            "pool_created_at": "2026-01-01T00:00:00Z",
            "base_token_price_usd": "0.001",
            "reserve_in_usd": "25000",
            "market_cap_usd": "100000",
            "fdv_usd": "100000",
            "volume_usd": {"m5": "100", "h1": "5000"},
            "transactions": {"m5": {"buys": 3, "sells": 1}, "h1": {"buys": 40, "sells": 20}},
            "price_change_percentage": {"m5": "1.5", "h1": "12"},
        },
        "relationships": {
            "base_token": {"data": {"id": "solana_TokenMint111"}},
            "quote_token": {"data": {"id": "solana_So11111111111111111111111111111111111111112"}},
            "dex": {"data": {"id": "solana_raydium"}},
        },
    }
    calls = {"page2": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            calls["page2"] += 1
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"data": [pool]})

    http, client = _http(handler, max_retries=3)
    provider = GeckoTerminalProvider(http, AsyncTTLCache(), ttl_seconds=1)
    pools = await provider.new_pools("solana", pages=2)
    assert [p.pool_address for p in pools] == ["pool-one"]
    assert calls["page2"] == 2  # one courtesy retry, then the page is skipped
    await client.aclose()

"""API contract tests: health, token listing, trades and the error envelope."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.db.session import session_scope
from app.main import create_app
from app.models import Pair, Token
from app.notifications.dispatcher import NotificationDispatcher
from app.providers.registry import Providers
from app.scanner.runner import ScannerRunner
from app.services.events import EventHub
from tests.helpers import add_snapshot


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(start_scanner=False)
    providers = Providers()
    hub = EventHub()
    dispatcher = NotificationDispatcher(providers.discord, hub)
    app.state.providers = providers
    app.state.hub = hub
    app.state.dispatcher = dispatcher
    app.state.scanner = ScannerRunner(providers, hub, dispatcher)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def test_health_reports_database_and_hard_limits(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["paper_only"] is True
    assert body["limits"] == {
        "initial_balance_usd": 10.0,
        "max_open_positions": 3,
        "max_position_usd": 2.5,
        "daily_loss_limit_usd": 0.5,
        "max_price_impact_pct": 1.0,
    }
    assert body["scanner"]["state"] == "stopped"


async def test_token_list_returns_seeded_opportunity(client, seed):
    token_id = await seed(symbol="API1", score=81.0)
    response = await client.get("/api/v1/tokens", params={"window_hours": 6, "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    row = body["tokens"][0]
    assert row["id"] == token_id
    assert row["symbol"] == "API1"
    assert row["score"]["score"] == pytest.approx(81.0)
    assert row["security"]["overall"] == "PASS"


async def test_token_list_picks_most_liquid_pair_for_every_token(client, seed):
    token_id = await seed(symbol="LIQ1", liquidity=5_000.0)
    async with session_scope() as session:
        token = await session.get(Token, token_id)
        assert token is not None
        session.add(
            Pair(
                token_id=token.id,
                chain=token.chain,
                pair_address="pool-deepest",
                dex_id="raydium",
                quote_symbol="SOL",
                base_symbol="LIQ1",
                price_usd=Decimal("0.002"),
                liquidity_usd=Decimal("480000"),
                market_cap_usd=Decimal("1000000"),
                fdv_usd=Decimal("1000000"),
            )
        )
        await session.flush()

    response = await client.get("/api/v1/tokens", params={"window_hours": 6, "limit": 10})
    assert response.status_code == 200
    row = response.json()["tokens"][0]
    assert row["pair"]["pair_address"] == "pool-deepest"
    assert row["pair"]["liquidity_usd"] == pytest.approx(480_000.0)


async def test_token_detail_and_history(client, seed):
    token_id = await seed(symbol="API2")
    detail = await client.get(f"/api/v1/tokens/{token_id}")
    assert detail.status_code == 200
    assert detail.json()["symbol"] == "API2"

    history = await client.get(f"/api/v1/tokens/{token_id}/history")
    assert history.status_code == 200
    assert history.json()["token_id"] == token_id
    assert len(history.json()["points"]) >= 1

    missing = await client.get("/api/v1/tokens/999999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


async def test_paper_buy_succeeds_and_respects_caps(client, seed):
    token_id = await seed(symbol="BUY1")
    response = await client.post(
        "/api/v1/paper-trades/buy", json={"token_id": token_id, "notional_usd": 2.5}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FILLED"
    assert body["estimated"] is True
    assert body["cash_balance"] < 10.0
    assert body["fees"]["total"] > 0

    oversized = await client.post(
        "/api/v1/paper-trades/buy", json={"token_id": token_id, "notional_usd": 3.0}
    )
    assert oversized.status_code == 409
    error = oversized.json()["error"]
    assert error["code"] == "POSITION_SIZE"
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["request_id"]


async def test_paper_sell_partial_then_full(client, seed):
    token_id = await seed(symbol="SELL1")
    bought = await client.post(
        "/api/v1/paper-trades/buy", json={"token_id": token_id, "notional_usd": 2.0}
    )
    position_id = bought.json()["position_id"]

    first = await client.post(
        "/api/v1/paper-trades/sell",
        json={"position_id": position_id, "ratio": 0.5, "exit_key": "api-half"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "OPEN"

    replay = await client.post(
        "/api/v1/paper-trades/sell",
        json={"position_id": position_id, "ratio": 0.5, "exit_key": "api-half"},
    )
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is True
    assert replay.json()["remaining_qty"] == pytest.approx(first.json()["remaining_qty"])

    final = await client.post(
        "/api/v1/paper-trades/sell",
        json={"position_id": position_id, "ratio": 1.0, "exit_key": "api-full"},
    )
    assert final.status_code == 200
    assert final.json()["status"] == "CLOSED"


async def test_tick_requires_the_shared_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "scanner_tick_token", "super-secret")
    denied = await client.post("/api/v1/scanner/tick")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "UNAUTHORIZED"

    wrong = await client.post("/api/v1/scanner/tick", headers={"X-Scan-Token": "nope"})
    assert wrong.status_code == 401


async def test_scanner_status_and_runs(client):
    status = await client.get("/api/v1/scanner/status")
    assert status.status_code == 200
    assert status.json()["state"] == "stopped"
    assert "providers" in status.json()

    runs = await client.get("/api/v1/scanner/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"] == []


async def test_validation_errors_use_the_error_envelope(client):
    response = await client.post("/api/v1/paper-trades/buy", json={"token_id": -1})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["errors"]


async def test_watchlist_round_trip(client, seed):
    token_id = await seed(symbol="WATCH1")
    added = await client.post(f"/api/v1/tokens/{token_id}/watchlist")
    assert added.status_code == 200
    assert added.json()["watched"] is True

    listing = await client.get("/api/v1/watchlist")
    assert listing.status_code == 200
    assert any(row["id"] == token_id for row in listing.json()["tokens"])

    removed = await client.delete(f"/api/v1/tokens/{token_id}/watchlist")
    assert removed.status_code == 200
    assert removed.json()["watched"] is False


async def test_portfolio_reflects_open_position(client, seed):
    token_id = await seed(symbol="PORT1")
    await client.post("/api/v1/paper-trades/buy", json={"token_id": token_id})

    summary = await client.get("/api/v1/portfolio")
    assert summary.status_code == 200
    body = summary.json()
    assert body["open_positions"] == 1
    assert body["max_open_positions"] == 3
    assert body["daily_loss_limit"] == pytest.approx(0.5)
    assert body["cash_balance"] < 10.0
    assert body["positions"][0]["symbol"] == "PORT1"

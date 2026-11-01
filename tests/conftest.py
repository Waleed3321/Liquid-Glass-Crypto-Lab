"""Pytest fixtures: every test gets its own SQLite database and $10 account.

The engine is created lazily from ``settings.database_url``, so pointing that
setting at a temporary file and disposing the engine gives full isolation
without touching the development database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from sqlalchemy import select

from app.core.clock import utc_now
from app.core.config import settings
from app.db.init import create_all, ensure_default_account
from app.db.session import dispose_engine, session_scope
from app.models import PaperAccount
from tests.helpers import seed_token

SeedCallable = Callable[..., Awaitable[int]]


@pytest.fixture(autouse=True)
async def isolated_database(tmp_path, monkeypatch) -> AsyncIterator[None]:
    db_file = tmp_path / "crypto_lab_test.sqlite3"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(settings, "scanner_enabled", False)
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "scanner_tick_token", "")
    monkeypatch.setattr(settings, "discord_webhook_url", "")
    monkeypatch.setattr(settings, "discord_bot_token", "")
    monkeypatch.setattr(settings, "discord_channel_id", "")
    await dispose_engine()
    await create_all()
    await ensure_default_account()
    yield
    await dispose_engine()


@pytest.fixture
def seed() -> SeedCallable:
    """Insert a fully tradeable token and return its id."""

    async def _seed(**kwargs) -> int:
        async with session_scope() as session:
            return await seed_token(session, **kwargs)

    return _seed


@pytest.fixture
async def account() -> PaperAccount:
    async with session_scope() as session:
        row = (
            await session.execute(select(PaperAccount).where(PaperAccount.name == "default"))
        ).scalar_one()
        return row


@pytest.fixture
def now():
    return utc_now()

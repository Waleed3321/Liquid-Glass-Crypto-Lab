"""The single transactional path through which every paper order passes.

SQLite: one process-wide asyncio lock plus ``BEGIN IMMEDIATE`` (WAL is enabled
at connection setup), so concurrent requests cannot interleave reads and writes.

PostgreSQL: a transaction-scoped advisory lock plus ``SELECT ... FOR UPDATE`` on
the account row. The advisory lock serialises the "count open positions" check
even when no rows exist yet.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models import PaperAccount
from app.repositories.trading import TradingRepository

logger = get_logger(__name__)

RISK_LOCK_KEY = 764_512_001
_locks: dict[int, asyncio.Lock] = {}


def _process_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _locks.get(id(loop))
    if lock is None:
        lock = asyncio.Lock()
        _locks[id(loop)] = lock
    return lock


@asynccontextmanager
async def risk_transaction(*, account_name: str = "default") -> AsyncIterator[tuple[AsyncSession, PaperAccount]]:
    async with _process_lock():
        factory = get_session_factory()
        async with factory() as session:
            try:
                if settings.is_sqlite:
                    try:
                        await session.execute(text("BEGIN IMMEDIATE"))
                    except Exception:  # pragma: no cover - driver already in a transaction
                        logger.debug("sqlite_begin_immediate_skipped")
                else:
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"), {"key": RISK_LOCK_KEY}
                    )

                repo = TradingRepository(session)
                account = await repo.account(name=account_name, for_update=not settings.is_sqlite)
                if account is None:
                    raise NotFoundError("Paper account has not been initialised.")

                yield session, account
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

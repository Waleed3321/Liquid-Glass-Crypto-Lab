"""Async engine/session factory with SQLite and PostgreSQL support."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _prepare_sqlite_path(url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return
    raw = url[len(prefix) :]
    if raw in {"", ":memory:"} or raw.startswith("file:"):
        return
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def _build_engine() -> AsyncEngine:
    url = settings.normalized_database_url
    if settings.is_sqlite:
        _prepare_sqlite_path(url)
        engine = create_async_engine(
            url,
            echo=settings.db_echo,
            future=True,
            connect_args={"timeout": 30},
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=8000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        return engine

    connect_args: dict[str, object] = {}
    if settings.is_pooled:
        # asyncpg keeps its own statement cache too; PgBouncer cannot reuse it.
        connect_args["statement_cache_size"] = 0
    return create_async_engine(
        url,
        echo=settings.db_echo,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=5,
        pool_recycle=1800,
        connect_args=connect_args,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, autoflush=False
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def ping_database() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

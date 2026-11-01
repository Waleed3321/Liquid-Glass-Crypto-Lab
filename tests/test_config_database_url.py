"""Provider connection strings must survive the trip into SQLAlchemy + asyncpg."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from app.core.config import Settings, _as_postgres_url

POOLED = (
    "postgresql://lab:pw@ep-flat-scene-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb"
    "?channel_binding=require&sslmode=require"
)
DIRECT = (
    "postgresql://lab:pw@ep-flat-scene.c-2.ap-southeast-1.aws.neon.tech/neondb"
    "?channel_binding=require&sslmode=require"
)


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def test_sqlite_urls_pass_through_untouched() -> None:
    url = "sqlite+aiosqlite:///./data/crypto_lab.db"
    assert _as_postgres_url(url) == url


def test_provider_scheme_is_rewritten_for_asyncpg() -> None:
    assert _as_postgres_url("postgres://lab:pw@host/db").startswith("postgresql+asyncpg://")
    assert _as_postgres_url("postgresql://lab:pw@host/db").startswith("postgresql+asyncpg://")


def test_asyncpg_incompatible_parameters_are_replaced() -> None:
    query = _query(_as_postgres_url(DIRECT))
    assert "channel_binding" not in query
    assert "sslmode" not in query
    assert query["ssl"] == ["require"]


def test_pooled_host_disables_the_prepared_statement_cache() -> None:
    query = _query(_as_postgres_url(POOLED))
    assert query["prepared_statement_cache_size"] == ["0"]
    assert query["ssl"] == ["require"]


def test_direct_host_keeps_the_prepared_statement_cache() -> None:
    assert "prepared_statement_cache_size" not in _query(_as_postgres_url(DIRECT))


def test_existing_ssl_setting_is_not_duplicated() -> None:
    url = _as_postgres_url("postgresql://lab:pw@host/db?sslmode=require&ssl=verify-full")
    assert _query(url)["ssl"] == ["verify-full"]


def _settings(**kwargs: str) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def test_runtime_and_migration_urls_use_different_endpoints() -> None:
    settings = _settings(database_url=POOLED, database_url_unpooled=DIRECT)
    assert settings.is_pooled is True
    assert "-pooler" in settings.normalized_database_url
    assert "-pooler" not in settings.migration_database_url


def test_migration_url_falls_back_to_the_runtime_url() -> None:
    settings = _settings(database_url=DIRECT, database_url_unpooled="")
    assert settings.is_pooled is False
    assert settings.migration_database_url == settings.normalized_database_url


def test_sqlite_is_not_treated_as_pooled() -> None:
    settings = _settings(database_url="sqlite+aiosqlite:///./data/crypto_lab.db")
    assert settings.is_sqlite is True
    assert settings.is_pooled is False

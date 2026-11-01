"""Centralised application configuration.

All values can be overridden with environment variables (see ``.env.example``).
Trading thresholds that users may tune at runtime live in
:mod:`app.strategies.config` and are persisted through the settings API.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

_SSL_MODES = {"require", "prefer", "verify-ca", "verify-full"}


def _as_postgres_url(raw: str) -> str:
    """Rewrite provider URLs into what SQLAlchemy's asyncpg dialect accepts."""
    url = raw
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not url.startswith("postgresql+asyncpg://"):
        return url

    parts = urlsplit(url)
    original = dict(parse_qsl(parts.query))
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        # asyncpg has no channel binding and rejects it as a connect argument.
        if key not in {"channel_binding", "sslmode"}
    ]
    # asyncpg takes `ssl`; map the libpq keyword the providers hand out.
    if original.get("sslmode", "").lower() in _SSL_MODES and not original.get("ssl"):
        query.append(("ssl", "require"))
    # Neon pools through PgBouncer in transaction mode, which cannot reuse
    # prepared statements across transactions: disable the dialect cache.
    if "-pooler" in (parts.hostname or "") and not original.get("prepared_statement_cache_size"):
        query.append(("prepared_statement_cache_size", "0"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # .env.local is written by `neon deploy`; it wins over .env.
        env_file=(str(BASE_DIR / ".env"), str(BASE_DIR / ".env.local")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Liquid Glass Crypto Lab"
    app_env: str = "development"
    version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"
    static_dir: Path = Field(default=BASE_DIR / "frontend")

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/crypto_lab.db"
    # Neon writes the direct (non-pooled) URL here; Alembic prefers it.
    database_url_unpooled: str = ""
    db_echo: bool = False
    db_pool_size: int = 5

    # HTTP
    cors_origins: str = "*"
    admin_token: str = ""

    # Scanner
    scanner_enabled: bool = True
    scan_interval_seconds: int = 60
    discovery_window_hours: float = 6.0
    min_tick_gap_seconds: int = 45
    scanner_tick_token: str = ""
    scanner_candidates_per_tick: int = 8
    scanner_security_refresh_per_tick: int = 4
    scanner_tick_timeout_seconds: int = 240
    gt_discovery_pages: int = 1
    ds_batch_size: int = 25
    max_ds_batches_per_tick: int = 2
    lease_ttl_seconds: int = 300

    # Paper account / hard risk limits
    initial_balance_usd: float = 10.0
    max_open_positions: int = 3
    max_position_usd: float = 2.5
    daily_loss_limit_usd: float = 0.5
    max_price_impact_pct: float = 1.0
    max_price_age_seconds: int = 120

    # Execution estimates
    sol_price_usd: float = 150.0
    bnb_price_usd: float = 600.0
    solana_network_fee_usd: float = 0.003
    bsc_network_fee_usd: float = 0.03
    dex_fee_pct: float = 0.25
    base_slippage_bps: float = 50.0
    slippage_impact_multiplier: float = 0.5
    solana_priority_fee_usd: float = 0.002
    bsc_gas_units: int = 210_000
    bsc_gas_price_gwei: float = 0.1

    # Providers
    geckoterminal_base_url: str = "https://api.geckoterminal.com/api/v2"
    dexscreener_base_url: str = "https://api.dexscreener.com"
    goplus_base_url: str = "https://api.gopluslabs.io/api/v1"
    rugcheck_base_url: str = "https://api.rugcheck.xyz/v1"
    http_timeout_seconds: float = 15.0
    http_max_retries: int = 3

    gt_rate_limit_per_min: int = 25
    ds_rate_limit_per_min: int = 50
    goplus_rate_limit_per_min: int = 20
    rugcheck_rate_limit_per_min: int = 12

    gt_cache_ttl_seconds: int = 55
    ds_cache_ttl_seconds: int = 40
    goplus_cache_ttl_seconds: int = 600
    rugcheck_cache_ttl_seconds: int = 300

    # Notifications
    discord_webhook_url: str = ""
    discord_bot_token: str = ""
    discord_channel_id: str = ""
    discord_enabled: bool = True
    discord_timeout_seconds: float = 10.0
    notification_max_attempts: int = 5

    # Retention
    snapshot_full_days: int = 7
    snapshot_raw_hours: int = 24

    # Daily loss accounting uses this UTC hour as the trading-day boundary.
    trading_day_rollover_hour: int = 0

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() in {"", "*"}:
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def normalized_database_url(self) -> str:
        """Runtime URL: pooled connections for application traffic."""
        return _as_postgres_url(self.database_url)

    @property
    def migration_database_url(self) -> str:
        """Alembic runs on the direct endpoint; pooling breaks DDL sessions."""
        return _as_postgres_url(self.database_url_unpooled or self.database_url)

    @property
    def is_pooled(self) -> bool:
        return "-pooler" in (urlsplit(self.normalized_database_url).hostname or "")

    def provider_rate_limits(self) -> dict[str, int]:
        return {
            "geckoterminal": self.gt_rate_limit_per_min,
            "dexscreener": self.ds_rate_limit_per_min,
            "goplus": self.goplus_rate_limit_per_min,
            "rugcheck": self.rugcheck_rate_limit_per_min,
        }

    def provider_cache_ttls(self) -> dict[str, int]:
        return {
            "geckoterminal": self.gt_cache_ttl_seconds,
            "dexscreener": self.ds_cache_ttl_seconds,
            "goplus": self.goplus_cache_ttl_seconds,
            "rugcheck": self.rugcheck_cache_ttl_seconds,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

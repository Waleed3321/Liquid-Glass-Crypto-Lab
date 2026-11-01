"""Market-side tables: tokens, pairs, snapshots, security checks, scores."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.db.base import Base
from app.db.types import UTCDateTime

MONEY = Numeric(24, 10)


def _zero() -> Decimal:
    return Decimal("0")


class Token(Base):
    __tablename__ = "tokens"
    __table_args__ = (
        UniqueConstraint("chain", "address", name="uq_tokens_chain_address"),
        Index("ix_tokens_chain_discovered", "chain", "first_discovered_at"),
        Index("ix_tokens_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chain: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    decimals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pair_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    first_discovered_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="geckoterminal", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Pair(Base):
    __tablename__ = "pairs"
    __table_args__ = (
        UniqueConstraint("chain", "pair_address", name="uq_pairs_chain_address"),
        Index("ix_pairs_token", "token_id"),
        Index("ix_pairs_liquidity", "liquidity_usd"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False
    )
    chain: Mapped[str] = mapped_column(String(16), nullable=False)
    pair_address: Mapped[str] = mapped_column(String(128), nullable=False)
    dex_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    quote_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    base_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    liquidity_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    market_cap_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    fdv_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    volume: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    txns: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    price_change: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint("pair_id", "ts", name="uq_snapshots_pair_ts"),
        Index("ix_snapshots_pair_ts", "pair_id", "ts"),
        Index("ix_snapshots_token_ts", "token_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False
    )
    pair_id: Mapped[int] = mapped_column(
        ForeignKey("pairs.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    liquidity_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    market_cap_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    fdv_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    volume_m5: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    volume_h1: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    volume_h6: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    volume_h24: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    buys_m5: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sells_m5: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    buys_h1: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sells_h1: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pct_m5: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pct_h1: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pct_h6: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pct_h24: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    txns: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    volume: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="dexscreener", nullable=False)
    scanner_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SecurityCheck(Base):
    __tablename__ = "security_checks"
    __table_args__ = (
        Index("ix_security_token_ts", "token_id", "ts"),
        Index("ix_security_overall", "overall"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False
    )
    chain: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="combined", nullable=False)
    overall: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    critical_pass: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    reasons: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class OpportunityScore(Base):
    __tablename__ = "opportunity_scores"
    __table_args__ = (
        Index("ix_scores_token_ts", "token_id", "ts"),
        Index("ix_scores_ts", "ts"),
        Index("ix_scores_score", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False
    )
    pair_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    security_risk: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    signal_strength: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rank_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    explanations: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), default="HOLD", nullable=False)
    rejection_codes: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)


class WatchlistEntry(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("token_id", name="uq_watchlist_token"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

"""Paper account, positions, orders, fills and daily performance."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.db.base import Base
from app.db.types import UTCDateTime

MONEY = Numeric(24, 10)


def _zero() -> Decimal:
    return Decimal("0")


class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    __table_args__ = (
        CheckConstraint("initial_balance > 0", name="ck_account_initial_positive"),
        CheckConstraint("cash_balance >= 0", name="ck_account_cash_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, default="default", nullable=False)
    initial_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("10"), nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("10"), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    is_halted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("entry_notional <= 2.5000000000", name="ck_position_max_notional"),
        CheckConstraint("remaining_qty >= 0", name="ck_position_remaining_non_negative"),
        Index("ix_positions_account_status", "account_id", "status"),
        Index("ix_positions_status", "status"),
        Index("ix_positions_token", "token_id"),
        Index(
            "uq_positions_open_token",
            "account_id",
            "token_id",
            unique=True,
            sqlite_where=text("status = 'OPEN'"),
            postgresql_where=text("status = 'OPEN'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False
    )
    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False
    )
    pair_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="OPEN", nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    remaining_qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    entry_notional: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    entry_fees: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    entry_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    invested_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    fees_paid: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    peak_price: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    trail_high: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    protection_armed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    strategy_version: Mapped[str] = mapped_column(String(32), default="A-1.0", nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    entry_snapshot_ts: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    entry_liquidity_usd: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_orders_client_id"),
        UniqueConstraint("exit_key", name="uq_orders_exit_key"),
        Index("ix_orders_account_created", "account_id", "created_at"),
        Index("ix_orders_position", "position_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False
    )
    token_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="NEW", nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(96), nullable=False)
    exit_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_notional: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    fill_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    fill_notional: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    reject_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    filled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Fill(Base):
    __tablename__ = "fills"
    __table_args__ = (Index("ix_fills_position", "position_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sector: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    notional: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_network: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    fee_dex: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    fee_tax: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    slippage_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impact_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    price_source_ts: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class DailyPerformance(Base):
    __tablename__ = "daily_performance"
    __table_args__ = (UniqueConstraint("account_id", "day", name="uq_daily_account_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    fees_paid: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    starting_equity: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    ending_equity: Mapped[Decimal] = mapped_column(MONEY, default=_zero, nullable=False)
    halted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

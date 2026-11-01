"""Decision log, scanner runs, notifications, settings and the scanner lease."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utc_now
from app.db.base import Base
from app.db.types import UTCDateTime


class StrategyDecision(Base):
    __tablename__ = "strategy_decisions"
    __table_args__ = (
        Index("ix_decisions_token_created", "token_id", "created_at"),
        Index("ix_decisions_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pair_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategy: Mapped[str] = mapped_column(String(32), default="A", nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    reason_codes: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )


class ScannerRun(Base):
    __tablename__ = "scanner_runs"
    __table_args__ = (Index("ix_runs_started", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="RUNNING", nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="loop", nullable=False)
    discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enriched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snapshots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class ScannerLease(Base):
    __tablename__ = "scanner_lease"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    owner: Mapped[str] = mapped_column(String(96), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_tick_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

"""Seed helpers shared by the test modules.

Everything here writes to the isolated test database created by
``tests/conftest.py``; no network access is involved.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.models import (
    DailyPerformance,
    MarketSnapshot,
    OpportunityScore,
    Pair,
    SecurityCheck,
    Token,
)
from app.services.security import CRITICAL_FIELDS

FIELD_VALUES: dict[str, Any] = {
    "honeypot": False,
    "mintable": False,
    "freezable": False,
    "lp_lock": 100.0,
    "buy_tax": 0.0,
    "sell_tax": 0.0,
    "ownership": "renounced",
}

RISK_BY_STATUS = {
    "PASS": 12.0,
    "WARNING": 45.0,
    "FAIL": 95.0,
    "UNKNOWN": 65.0,
    "UNAVAILABLE": 80.0,
}


def make_security_fields(
    chain: str = "solana",
    overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a complete PASS field map, then apply per-field overrides."""

    fields: dict[str, dict[str, Any]] = {}
    for name in CRITICAL_FIELDS[chain]:
        fields[name] = {
            "name": name,
            "status": "PASS",
            "value": FIELD_VALUES[name],
            "reason": "verified by fake provider",
            "source": "fake",
        }
    fields["holder_concentration"] = {
        "name": "holder_concentration",
        "status": "PASS",
        "value": 25.0,
        "reason": "top 10 hold 25%",
        "source": "fake",
    }
    fields["holder_count"] = {
        "name": "holder_count",
        "status": "PASS",
        "value": 420,
        "reason": "420 holders",
        "source": "fake",
    }
    for name, patch in (overrides or {}).items():
        base = fields.get(
            name,
            {"name": name, "status": "PASS", "value": None, "reason": "", "source": "fake"},
        )
        fields[name] = {**base, **patch}
    return fields


def _dec(value: float | Decimal) -> Decimal:
    return Decimal(str(value))


async def seed_token(
    session: AsyncSession,
    *,
    chain: str = "solana",
    price: float = 0.001,
    liquidity: float = 50_000.0,
    symbol: str | None = None,
    security: str | None = "PASS",
    field_overrides: dict[str, dict[str, Any]] | None = None,
    snapshot_ts: datetime | None = None,
    security_ts: datetime | None = None,
    volume_h1: float | None = None,
    buys_h1: int = 120,
    sells_h1: int = 60,
    pct_m5: float = 1.0,
    pct_h1: float = 20.0,
    score: float = 78.0,
    confidence: float = 0.8,
    decision: str = "HOLD",
    add_score: bool = True,
    first_discovered_at: datetime | None = None,
) -> int:
    """Insert one token with pair, snapshot, security check and score."""

    now = utc_now()
    symbol = symbol or f"T{uuid.uuid4().hex[:4].upper()}"
    discovered = first_discovered_at or (now - timedelta(minutes=20))
    token = Token(
        chain=chain,
        address=f"{chain}-{uuid.uuid4().hex[:12]}",
        symbol=symbol,
        name=f"{symbol} Test Token",
        pair_created_at=discovered,
        first_discovered_at=discovered,
        last_seen_at=now,
        source="test",
    )
    session.add(token)
    await session.flush()

    hourly_volume = volume_h1 if volume_h1 is not None else liquidity * 0.4
    volume = {
        "m5": liquidity * 0.02,
        "h1": hourly_volume,
        "h6": hourly_volume * 3,
        "h24": hourly_volume * 9,
    }
    txns = {
        "m5": {"buys": 12, "sells": 6},
        "h1": {"buys": buys_h1, "sells": sells_h1},
    }
    pair = Pair(
        token_id=token.id,
        chain=chain,
        pair_address=f"pool-{uuid.uuid4().hex[:12]}",
        dex_id="raydium" if chain == "solana" else "pancakeswap",
        quote_symbol="SOL" if chain == "solana" else "WBNB",
        base_symbol=symbol,
        price_usd=_dec(price),
        liquidity_usd=_dec(liquidity),
        market_cap_usd=_dec(price * 1_000_000),
        fdv_usd=_dec(price * 1_000_000),
        volume=volume,
        txns=txns,
        price_change={"m5": pct_m5, "h1": pct_h1, "h6": pct_h1 * 2, "h24": pct_h1 * 3},
    )
    session.add(pair)
    await session.flush()

    session.add(
        MarketSnapshot(
            token_id=token.id,
            pair_id=pair.id,
            ts=snapshot_ts or now,
            price_usd=_dec(price),
            liquidity_usd=_dec(liquidity),
            market_cap_usd=_dec(price * 1_000_000),
            fdv_usd=_dec(price * 1_000_000),
            volume_m5=_dec(volume["m5"]),
            volume_h1=_dec(volume["h1"]),
            volume_h6=_dec(volume["h6"]),
            volume_h24=_dec(volume["h24"]),
            buys_m5=12,
            sells_m5=6,
            buys_h1=buys_h1,
            sells_h1=sells_h1,
            pct_m5=pct_m5,
            pct_h1=pct_h1,
            pct_h6=pct_h1 * 2,
            pct_h24=pct_h1 * 3,
            txns=txns,
            volume=volume,
            source="test",
        )
    )

    if security is not None:
        fields = make_security_fields(chain, field_overrides)
        unknowns = sum(
            1
            for name in CRITICAL_FIELDS[chain]
            if fields.get(name, {}).get("status") not in {"PASS", "WARNING", "FAIL"}
            or fields.get(name) is None
        )
        session.add(
            SecurityCheck(
                token_id=token.id,
                chain=chain,
                ts=security_ts or now,
                provider="combined",
                overall=security,
                risk_score=RISK_BY_STATUS.get(security, 65.0),
                critical_pass=len(CRITICAL_FIELDS[chain]) - unknowns,
                critical_total=len(CRITICAL_FIELDS[chain]),
                fields=fields,
                reasons=["Seeded security fixture."],
                raw={"providers": {"goplus": True, "rugcheck": chain == "solana"}},
            )
        )

    if add_score:
        session.add(
            OpportunityScore(
                token_id=token.id,
                pair_id=pair.id,
                ts=now,
                score=score,
                confidence=confidence,
                security_risk=RISK_BY_STATUS.get(security or "UNKNOWN", 65.0),
                signal_strength=0.61,
                rank_score=round(score * confidence, 4),
                components={
                    "liquidity": 22.0,
                    "volume": 14.0,
                    "activity": 10.0,
                    "holders": 11.0,
                    "momentum": 9.0,
                    "security": 10.0,
                },
                explanations=["Seeded score fixture."],
                decision=decision,
                rejection_codes=[],
            )
        )
    await session.flush()
    return token.id


async def add_snapshot(
    session: AsyncSession,
    token_id: int,
    *,
    price: float,
    liquidity: float = 50_000.0,
    ts: datetime | None = None,
    pct_m5: float = 0.0,
    pct_h1: float = 20.0,
    buys_h1: int = 120,
    sells_h1: int = 60,
    volume_h1: float | None = None,
) -> None:
    token = await session.get(Token, token_id)
    pair = (
        await session.execute(
            select(Pair).where(Pair.token_id == token_id).order_by(Pair.id.asc())
        )
    ).scalars().first()
    assert token is not None and pair is not None
    hourly = volume_h1 if volume_h1 is not None else liquidity * 0.4
    session.add(
        MarketSnapshot(
            token_id=token.id,
            pair_id=pair.id,
            ts=ts or utc_now(),
            price_usd=_dec(price),
            liquidity_usd=_dec(liquidity),
            volume_m5=_dec(hourly * 0.05),
            volume_h1=_dec(hourly),
            volume_h6=_dec(hourly * 3),
            volume_h24=_dec(hourly * 9),
            buys_m5=12,
            sells_m5=6,
            buys_h1=buys_h1,
            sells_h1=sells_h1,
            pct_m5=pct_m5,
            pct_h1=pct_h1,
            pct_h6=pct_h1 * 2,
            pct_h24=pct_h1 * 3,
            txns={"h1": {"buys": buys_h1, "sells": sells_h1}},
            volume={"m5": hourly * 0.05, "h1": hourly, "h6": hourly * 3, "h24": hourly * 9},
            source="test",
        )
    )
    await session.flush()


async def set_today_daily(
    session: AsyncSession,
    account_id: int,
    *,
    realized: float,
    halted: bool = False,
    day=None,
) -> DailyPerformance:
    row = await session.execute(
        select(DailyPerformance).where(
            DailyPerformance.account_id == account_id,
            DailyPerformance.day == (day or utc_now().date()),
        )
    )
    existing = row.scalar_one_or_none()
    if existing is None:
        existing = DailyPerformance(
            account_id=account_id,
            day=day or utc_now().date(),
            realized_pnl=_dec(realized),
            halted=halted,
        )
        session.add(existing)
    else:
        existing.realized_pnl = _dec(realized)
        existing.halted = halted
    await session.flush()
    return existing


def utc_datetime(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)

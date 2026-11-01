"""Seed the local acceptance database with clearly-labelled demo tokens.

The scanner discovers real tokens from GeckoTerminal; those rarely pass every
security gate, so a synthetic, PASS-security token is needed to exercise the
buy / take-profit / stop-loss flows locally. Every row created here uses
``source="seed"`` and a ``DEMO-`` contract address so it can never be confused
with real market data. Demo rows are deleted by ``seed.py reset``.

Usage::

    uv run python scripts/seed.py reset
    uv run python scripts/seed.py list
    uv run python scripts/seed.py bump --token-id 7 --pct 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.clock import utc_now  # noqa: E402
from app.db.init import init_database  # noqa: E402
from app.db.session import dispose_engine, session_scope  # noqa: E402
from app.models import (  # noqa: E402
    MarketSnapshot,
    OpportunityScore,
    Pair,
    SecurityCheck,
    StrategyDecision,
    Token,
)
from app.services.security import CRITICAL_FIELDS  # noqa: E402

BASE_PRICE = 0.001
GOLDEN = [1.00, 1.02, 1.04, 1.06, 1.09, 1.12, 1.15, 1.18, 1.20, 1.18, 1.15, 1.12, 1.10, 1.11]
FLAT = [1.00, 1.005, 1.00, 1.005, 1.00, 1.005, 1.00, 1.005]

PROFILES = ("demo", "vertical", "unsafe", "stale", "trade", "stop", "extra1", "extra2")

FIELD_VALUES = {
    "honeypot": False,
    "mintable": False,
    "freezable": False,
    "lp_lock": 100.0,
    "buy_tax": 0.0,
    "sell_tax": 0.0,
    "ownership": "renounced",
}


def _dec(value: float | Decimal) -> Decimal:
    return Decimal(str(value))


def _fields(*, honeypot_fail: bool = False) -> dict[str, dict]:
    fields = {}
    for name in CRITICAL_FIELDS["solana"]:
        status = "FAIL" if (name == "honeypot" and honeypot_fail) else "PASS"
        value = True if (name == "honeypot" and honeypot_fail) else FIELD_VALUES[name]
        fields[name] = {
            "name": name,
            "status": status,
            "value": value,
            "reason": "seeded demo field" if status == "PASS" else "demo honeypot",
            "source": "seed",
        }
    fields["holder_concentration"] = {
        "name": "holder_concentration",
        "status": "PASS",
        "value": 25.0,
        "reason": "seeded demo distribution",
        "source": "seed",
    }
    fields["holder_count"] = {
        "name": "holder_count",
        "status": "PASS",
        "value": 800,
        "reason": "seeded demo distribution",
        "source": "seed",
    }
    return fields


async def _drop_demo_tokens() -> int:
    removed = 0
    async with session_scope() as session:
        tokens = (
            await session.execute(select(Token).where(Token.address.like("DEMO-%")))
        ).scalars().all()
        token_ids = [token.id for token in tokens]
        if token_ids:
            for decision in (
                await session.execute(
                    select(StrategyDecision).where(StrategyDecision.token_id.in_(token_ids))
                )
            ).scalars().all():
                await session.delete(decision)
        for token in tokens:
            await session.delete(token)
            removed += 1
    return removed


async def _insert_profile(session, profile: str) -> Token:
    now = utc_now()
    if profile == "demo":
        series, liquidity, volume, pct_m5, pct_h1, security = GOLDEN, 60_000.0, 30_000.0, 1.0, 20.0, "PASS"
    elif profile == "vertical":
        series = GOLDEN[:-1] + [GOLDEN[-1] * 1.25]
        liquidity, volume, pct_m5, pct_h1, security = 60_000.0, 30_000.0, 25.0, 20.0, "PASS"
    elif profile == "unsafe":
        series, liquidity, volume, pct_m5, pct_h1, security = GOLDEN, 60_000.0, 30_000.0, 1.0, 20.0, "FAIL"
    elif profile == "stale":
        series = FLAT[-1:]
        liquidity, volume, pct_m5, pct_h1, security = 60_000.0, 30_000.0, 0.0, 0.0, "PASS"
    else:
        series = FLAT
        liquidity, volume, pct_m5, pct_h1, security = 80_000.0, 40_000.0, 0.5, 2.0, "PASS"

    # End on "now" so a tick one minute later is still inside the observation gap.
    start = now - timedelta(seconds=5, minutes=0 if profile == "stale" else len(series) - 1)
    if profile == "stale":
        start = now - timedelta(minutes=15)

    price = BASE_PRICE * series[-1]
    token = Token(
        chain="solana",
        address=f"DEMO-{profile.upper()}",
        symbol=f"D{profile.upper()[:6]}",
        name=f"Demo {profile.title()} Token",
        pair_created_at=now - timedelta(minutes=30),
        first_discovered_at=now - timedelta(minutes=30),
        last_seen_at=now,
        source="seed",
    )
    session.add(token)
    await session.flush()

    pair = Pair(
        token_id=token.id,
        chain="solana",
        pair_address=f"DEMO-POOL-{profile.upper()}",
        dex_id="raydium",
        quote_symbol="SOL",
        base_symbol=token.symbol,
        price_usd=_dec(price),
        liquidity_usd=_dec(liquidity),
        market_cap_usd=_dec(price * 1_000_000),
        fdv_usd=_dec(price * 1_000_000),
        volume={"m5": volume / 12, "h1": volume, "h6": volume * 3, "h24": volume * 9},
        txns={"m5": {"buys": 12, "sells": 6}, "h1": {"buys": 140, "sells": 70}},
        price_change={"m5": pct_m5, "h1": pct_h1, "h6": pct_h1 * 2, "h24": pct_h1 * 3},
    )
    session.add(pair)
    await session.flush()

    for index, factor in enumerate(series):
        ts = start + timedelta(minutes=index)
        session.add(
            MarketSnapshot(
                token_id=token.id,
                pair_id=pair.id,
                ts=ts,
                price_usd=_dec(BASE_PRICE * factor),
                liquidity_usd=_dec(liquidity),
                market_cap_usd=_dec(BASE_PRICE * factor * 1_000_000),
                fdv_usd=_dec(BASE_PRICE * factor * 1_000_000),
                volume_m5=_dec(volume / 12),
                volume_h1=_dec(volume),
                volume_h6=_dec(volume * 3),
                volume_h24=_dec(volume * 9),
                buys_m5=12,
                sells_m5=6,
                buys_h1=140,
                sells_h1=70,
                pct_m5=pct_m5 if index == len(series) - 1 else 0.0,
                pct_h1=pct_h1 if index == len(series) - 1 else 0.0,
                txns={"h1": {"buys": 140, "sells": 70}},
                volume={"m5": volume / 12, "h1": volume, "h6": volume * 3, "h24": volume * 9},
                source="seed",
            )
        )

    session.add(
        SecurityCheck(
            token_id=token.id,
            chain="solana",
            ts=now,
            provider="combined",
            overall=security,
            risk_score=12.0 if security == "PASS" else 95.0,
            critical_pass=len(CRITICAL_FIELDS["solana"]) - (0 if security == "PASS" else 1),
            critical_total=len(CRITICAL_FIELDS["solana"]),
            fields=_fields(honeypot_fail=security == "FAIL"),
            reasons=["Seeded demo security record (not a real token)."],
            raw={"providers": {"goplus": True, "rugcheck": True}},
        )
    )
    session.add(
        OpportunityScore(
            token_id=token.id,
            pair_id=pair.id,
            ts=now,
            score=82.0,
            confidence=0.9,
            security_risk=12.0 if security == "PASS" else 95.0,
            signal_strength=0.6,
            rank_score=73.8,
            components={
                "liquidity": 22.0,
                "volume": 14.0,
                "activity": 11.0,
                "holders": 15.0,
                "momentum": 12.0,
                "security": 10.0,
            },
            explanations=["Seeded demo score (not a real token)."],
            decision="HOLD",
            rejection_codes=[],
        )
    )
    await session.flush()
    return token


async def reset() -> None:
    removed = await _drop_demo_tokens()
    ids: dict[str, int] = {}
    async with session_scope() as session:
        for profile in PROFILES:
            token = await _insert_profile(session, profile)
            ids[profile] = token.id
    print(json.dumps({"removed": removed, "seed_tokens": ids}, indent=2))


async def list_demo() -> None:
    async with session_scope() as session:
        rows = (
            await session.execute(select(Token).where(Token.address.like("DEMO-%")))
        ).scalars().all()
        payload = [
            {"id": token.id, "address": token.address, "symbol": token.symbol}
            for token in rows
        ]
    print(json.dumps(payload, indent=2))


async def bump(token_id: int, pct: float) -> None:
    async with session_scope() as session:
        token = await session.get(Token, token_id)
        if token is None:
            raise SystemExit(f"Token {token_id} not found")
        pair = (
            await session.execute(
                select(Pair).where(Pair.token_id == token_id).order_by(Pair.id.asc())
            )
        ).scalars().first()
        if pair is None:
            raise SystemExit(f"Token {token_id} has no pair")
        new_price = float(pair.price_usd) * (1 + pct / 100.0)
        now = utc_now()
        pair.price_usd = _dec(new_price)
        pair.price_change = {"m5": pct, "h1": pct, "h6": pct, "h24": pct}
        for volume_key in ("m5", "h1", "h6", "h24"):
            pair.volume[volume_key] = float(pair.volume.get(volume_key, 0) or 0)
        session.add(
            MarketSnapshot(
                token_id=token.id,
                pair_id=pair.id,
                ts=now,
                price_usd=_dec(new_price),
                liquidity_usd=pair.liquidity_usd,
                market_cap_usd=_dec(new_price * 1_000_000),
                fdv_usd=_dec(new_price * 1_000_000),
                volume_m5=_dec(float(pair.volume.get("m5", 0) or 0)),
                volume_h1=_dec(float(pair.volume.get("h1", 0) or 0)),
                volume_h6=_dec(float(pair.volume.get("h6", 0) or 0)),
                volume_h24=_dec(float(pair.volume.get("h24", 0) or 0)),
                buys_m5=12,
                sells_m5=6,
                buys_h1=140,
                sells_h1=70,
                pct_m5=pct,
                pct_h1=pct,
                txns={"h1": {"buys": 140, "sells": 70}},
                volume=pair.volume,
                source="seed",
            )
        )
    print(json.dumps({"token_id": token_id, "new_price": new_price}, indent=2))


async def refresh() -> None:
    """Re-stamp seeded rows so an old demo token becomes fresh again."""
    now = utc_now()
    refreshed: dict[str, float] = {}
    async with session_scope() as session:
        tokens = (
            await session.execute(select(Token).where(Token.address.like("DEMO-%")))
        ).scalars().all()
        for token in tokens:
            snapshots = (
                await session.execute(
                    select(MarketSnapshot)
                    .where(MarketSnapshot.token_id == token.id)
                    .order_by(MarketSnapshot.ts.asc())
                )
            ).scalars().all()
            if not snapshots:
                continue
            delta = now - snapshots[-1].ts
            for snapshot in snapshots:
                snapshot.ts = snapshot.ts + delta
            security = "FAIL" if token.address.endswith("UNSAFE") else "PASS"
            session.add(
                SecurityCheck(
                    token_id=token.id,
                    chain=token.chain,
                    ts=now,
                    provider="combined",
                    overall=security,
                    risk_score=12.0 if security == "PASS" else 95.0,
                    critical_pass=len(CRITICAL_FIELDS["solana"]) - (0 if security == "PASS" else 1),
                    critical_total=len(CRITICAL_FIELDS["solana"]),
                    fields=_fields(honeypot_fail=security == "FAIL"),
                    reasons=["Seeded demo security record (refreshed)."],
                    raw={"providers": {"goplus": True, "rugcheck": True}},
                )
            )
            for row in (
                await session.execute(
                    select(OpportunityScore).where(OpportunityScore.token_id == token.id)
                )
            ).scalars().all():
                row.ts = now
            token.last_seen_at = now
            refreshed[token.address] = round(delta.total_seconds(), 1)
    print(json.dumps({"refreshed_seconds": refreshed}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset", help="delete demo tokens and re-seed all profiles")
    sub.add_parser("list", help="list demo tokens")
    sub.add_parser("refresh", help="shift demo timestamps so the rows look fresh")
    bump_parser = sub.add_parser("bump", help="apply a synthetic price move")
    bump_parser.add_argument("--token-id", type=int, required=True)
    bump_parser.add_argument("--pct", type=float, required=True)

    args = parser.parse_args()

    async def runner() -> None:
        await init_database()
        try:
            if args.command == "reset":
                await reset()
            elif args.command == "list":
                await list_demo()
            elif args.command == "refresh":
                await refresh()
            elif args.command == "bump":
                await bump(args.token_id, args.pct)
        finally:
            await dispose_engine()

    asyncio.run(runner())


if __name__ == "__main__":
    main()

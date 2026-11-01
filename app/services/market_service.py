"""Read models for tokens, watchlist and market intelligence."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.models import (
    MarketSnapshot,
    OpportunityScore,
    Pair,
    Position,
    SecurityCheck,
    StrategyDecision,
    Token,
    WatchlistEntry,
)
from app.models.enums import PositionStatus
from app.repositories.tokens import TokenRepository


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _age_minutes(token: Token) -> float | None:
    reference = token.pair_created_at or token.first_discovered_at
    if reference is None:
        return None
    return round((utc_now() - reference).total_seconds() / 60.0, 1)


def _pair_dict(pair: Pair | None) -> dict[str, Any] | None:
    if pair is None:
        return None
    return {
        "id": pair.id,
        "pair_address": pair.pair_address,
        "dex_id": pair.dex_id,
        "quote_symbol": pair.quote_symbol,
        "price_usd": _f(pair.price_usd),
        "liquidity_usd": _f(pair.liquidity_usd),
        "market_cap_usd": _f(pair.market_cap_usd),
        "fdv_usd": _f(pair.fdv_usd),
        "volume": pair.volume or {},
        "txns": pair.txns or {},
        "price_change": pair.price_change or {},
        "last_updated_at": _iso(pair.last_updated_at),
        "is_active": pair.is_active,
    }


def _security_dict(check: SecurityCheck | None) -> dict[str, Any] | None:
    if check is None:
        return None
    return {
        "overall": check.overall,
        "risk_score": _f(check.risk_score),
        "critical_pass": check.critical_pass,
        "critical_total": check.critical_total,
        "fields": check.fields or {},
        "reasons": check.reasons or [],
        "ts": _iso(check.ts),
        "provider": check.provider,
    }


def _score_dict(score: OpportunityScore | None) -> dict[str, Any] | None:
    if score is None:
        return None
    return {
        "score": _f(score.score),
        "confidence": _f(score.confidence),
        "security_risk": _f(score.security_risk),
        "signal_strength": _f(score.signal_strength),
        "rank_score": _f(score.rank_score),
        "components": score.components or {},
        "explanations": score.explanations or [],
        "decision": score.decision,
        "rejection_codes": score.rejection_codes or [],
        "ts": _iso(score.ts),
    }


def token_row(
    token: Token,
    *,
    pair: Pair | None,
    snapshot: MarketSnapshot | None,
    score: OpportunityScore | None,
    check: SecurityCheck | None,
    in_watchlist: bool = False,
    has_position: bool = False,
) -> dict[str, Any]:
    price = _f(snapshot.price_usd) if snapshot else _f(pair.price_usd if pair else 0)
    liquidity = _f(snapshot.liquidity_usd) if snapshot else _f(pair.liquidity_usd if pair else 0)
    return {
        "id": token.id,
        "chain": token.chain,
        "chain_label": "Solana" if token.chain == "solana" else "BNB Chain",
        "address": token.address,
        "symbol": token.symbol,
        "name": token.name,
        "image_url": token.image_url,
        "website_url": token.website_url,
        "pair_created_at": _iso(token.pair_created_at),
        "first_discovered_at": _iso(token.first_discovered_at),
        "last_seen_at": _iso(token.last_seen_at),
        "age_minutes": _age_minutes(token),
        "is_active": token.is_active,
        "pair": _pair_dict(pair),
        "price_usd": price,
        "liquidity_usd": liquidity,
        "market_cap_usd": _f(snapshot.market_cap_usd) if snapshot else _f(pair.market_cap_usd if pair else 0),
        "fdv_usd": _f(snapshot.fdv_usd) if snapshot else _f(pair.fdv_usd if pair else 0),
        "volume_m5": _f(snapshot.volume_m5) if snapshot else 0.0,
        "volume_h1": _f(snapshot.volume_h1) if snapshot else 0.0,
        "volume_h6": _f(snapshot.volume_h6) if snapshot else 0.0,
        "buys_m5": snapshot.buys_m5 if snapshot else 0,
        "sells_m5": snapshot.sells_m5 if snapshot else 0,
        "buys_h1": snapshot.buys_h1 if snapshot else 0,
        "sells_h1": snapshot.sells_h1 if snapshot else 0,
        "pct_m5": _f(snapshot.pct_m5) if snapshot else 0.0,
        "pct_h1": _f(snapshot.pct_h1) if snapshot else 0.0,
        "pct_h6": _f(snapshot.pct_h6) if snapshot else 0.0,
        "snapshot_ts": _iso(snapshot.ts) if snapshot else None,
        "security": _security_dict(check),
        "score": _score_dict(score),
        "data_confidence": _f(score.confidence) if score else 0.0,
        "strategy_signal": score.decision if score else "HOLD",
        "rejection_reason": (score.rejection_codes[0] if score and score.rejection_codes else None),
        "in_watchlist": in_watchlist,
        "has_position": has_position,
    }


async def _context(
    session: AsyncSession, tokens: Sequence[Token]
) -> tuple[
    dict[int, Pair],
    dict[int, MarketSnapshot],
    dict[int, OpportunityScore],
    dict[int, SecurityCheck],
    set[int],
    set[int],
]:
    repo = TokenRepository(session)
    ids = [token.id for token in tokens]
    pairs = await repo.primary_pairs(ids)
    snapshots = await repo.latest_snapshots(ids)
    scores = await repo.latest_scores(ids)
    checks = await repo.latest_security(ids)
    watchlist = set(
        (
            await session.execute(
                select(WatchlistEntry.token_id).where(WatchlistEntry.token_id.in_(ids))
            )
        )
        .scalars()
        .all()
    )
    positions = set(
        (
            await session.execute(
                select(Position.token_id).where(
                    Position.token_id.in_(ids),
                    Position.status == PositionStatus.OPEN.value,
                )
            )
        )
        .scalars()
        .all()
    )
    return pairs, snapshots, scores, checks, watchlist, positions


async def list_tokens(
    session: AsyncSession,
    *,
    chain: str | None = None,
    search: str | None = None,
    min_score: float | None = None,
    security: str | None = None,
    signal: str | None = None,
    watchlist_only: bool = False,
    with_position: bool | None = None,
    window_hours: float | None = None,
    sort: str = "score",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    query = select(Token).where(Token.is_active.is_(True))
    if chain in {"solana", "bsc"}:
        query = query.where(Token.chain == chain)
    if window_hours:
        query = query.where(Token.first_discovered_at >= utc_now() - timedelta(hours=window_hours))
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(
            or_(
                Token.symbol.ilike(needle),
                Token.name.ilike(needle),
                Token.address.ilike(needle),
            )
        )
    if watchlist_only:
        query = query.where(
            Token.id.in_(select(WatchlistEntry.token_id))
        )
    tokens = list(
        (await session.execute(query.order_by(Token.first_discovered_at.desc()).limit(600)))
        .scalars()
        .all()
    )

    pairs, snapshots, scores, checks, watchlist, positions = await _context(session, tokens)
    rows = []
    for token in tokens:
        row = token_row(
            token,
            pair=pairs.get(token.id),
            snapshot=snapshots.get(token.id),
            score=scores.get(token.id),
            check=checks.get(token.id),
            in_watchlist=token.id in watchlist,
            has_position=token.id in positions,
        )
        if min_score is not None and (row["score"] or {}).get("score", 0) < min_score:
            continue
        if security and (row["security"] or {}).get("overall") != security:
            continue
        if signal and row["strategy_signal"] != signal:
            continue
        if with_position is not None and row["has_position"] != with_position:
            continue
        rows.append(row)

    sort_keys = {
        "score": lambda r: (r["score"] or {}).get("score", 0),
        "confidence": lambda r: r["data_confidence"],
        "liquidity": lambda r: r["liquidity_usd"],
        "volume": lambda r: r["volume_h1"],
        "price_change": lambda r: r["pct_h1"],
        "discovered": lambda r: r["first_discovered_at"] or "",
        "age": lambda r: r["age_minutes"] or 0,
        "symbol": lambda r: (r["symbol"] or "").lower(),
        "risk": lambda r: (r["security"] or {}).get("risk_score", 100),
    }
    key = sort_keys.get(sort, sort_keys["score"])
    rows.sort(key=key, reverse=(order != "asc"))

    total = len(rows)
    page = rows[offset : offset + limit]
    return {"total": total, "limit": limit, "offset": offset, "tokens": page, "as_of": utc_now().isoformat()}


async def token_detail(session: AsyncSession, token_id: int) -> dict[str, Any] | None:
    repo = TokenRepository(session)
    token = await repo.get(token_id)
    if token is None:
        return None
    pair = await repo.primary_pair(token_id)
    snapshot = await repo.latest_snapshot(pair.id) if pair else None
    scores = await repo.latest_scores([token_id])
    checks = await repo.latest_security([token_id])
    watchlist = await session.execute(
        select(WatchlistEntry).where(WatchlistEntry.token_id == token_id)
    )
    position = await session.execute(
        select(Position).where(
            Position.token_id == token_id, Position.status == PositionStatus.OPEN.value
        )
    )
    decisions = list(
        (
            await session.execute(
                select(StrategyDecision)
                .where(StrategyDecision.token_id == token_id)
                .order_by(StrategyDecision.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    row = token_row(
        token,
        pair=pair,
        snapshot=snapshot,
        score=scores.get(token_id),
        check=checks.get(token_id),
        in_watchlist=watchlist.scalar_one_or_none() is not None,
        has_position=position.scalar_one_or_none() is not None,
    )
    row["decisions"] = [
        {
            "id": d.id,
            "action": d.action,
            "reason_codes": d.reason_codes or [],
            "metrics": d.metrics or {},
            "created_at": _iso(d.created_at),
        }
        for d in decisions
    ]
    row["links"] = {
        "dexscreener": (
            f"https://dexscreener.com/{token.chain}/{pair.pair_address}" if pair else None
        ),
        "explorer": (
            f"https://solscan.io/token/{token.address}"
            if token.chain == "solana"
            else f"https://bscscan.com/token/{token.address}"
        ),
    }
    return row


async def token_history(
    session: AsyncSession, token_id: int, *, hours: float = 6.0, limit: int = 500
) -> dict[str, Any] | None:
    repo = TokenRepository(session)
    token = await repo.get(token_id)
    if token is None:
        return None
    pair = await repo.primary_pair(token_id)
    if pair is None:
        return {"token_id": token_id, "pair": None, "points": [], "scores": []}
    since = utc_now() - timedelta(hours=hours)
    rows = await repo.snapshots_for_pair(pair.id, since=since, limit=limit)
    score_rows = list(
        (
            await session.execute(
                select(OpportunityScore)
                .where(OpportunityScore.token_id == token_id, OpportunityScore.ts >= since)
                .order_by(OpportunityScore.ts.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "token_id": token_id,
        "symbol": token.symbol,
        "chain": token.chain,
        "pair": _pair_dict(pair),
        "points": [
            {
                "ts": _iso(row.ts),
                "price": _f(row.price_usd),
                "liquidity": _f(row.liquidity_usd),
                "volume_h1": _f(row.volume_h1),
                "buys_h1": row.buys_h1,
                "sells_h1": row.sells_h1,
                "pct_m5": _f(row.pct_m5),
                "pct_h1": _f(row.pct_h1),
            }
            for row in rows
        ],
        "scores": [
            {"ts": _iso(row.ts), "score": _f(row.score), "confidence": _f(row.confidence)}
            for row in score_rows
        ],
    }


async def watchlist_view(session: AsyncSession) -> dict[str, Any]:
    ids = list((await session.execute(select(WatchlistEntry.token_id))).scalars().all())
    if not ids:
        return {"total": 0, "tokens": [], "as_of": utc_now().isoformat()}
    result = await list_tokens(session, watchlist_only=True, limit=200, sort="discovered")
    return result


async def analytics(session: AsyncSession) -> dict[str, Any]:
    window = utc_now() - timedelta(hours=6)
    tokens = list(
        (await session.execute(select(Token).where(Token.first_discovered_at >= window)))
        .scalars()
        .all()
    )
    pairs, snapshots, scores, checks, watchlist, positions = await _context(session, tokens)
    by_chain: dict[str, int] = {}
    security_counts: dict[str, int] = {}
    buckets = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    rejection_codes: dict[str, int] = {}
    rows = []
    for token in tokens:
        row = token_row(
            token,
            pair=pairs.get(token.id),
            snapshot=snapshots.get(token.id),
            score=scores.get(token.id),
            check=checks.get(token.id),
            in_watchlist=token.id in watchlist,
            has_position=token.id in positions,
        )
        rows.append(row)
        by_chain[token.chain] = by_chain.get(token.chain, 0) + 1
        status = (row["security"] or {}).get("overall", "UNKNOWN")
        security_counts[status] = security_counts.get(status, 0) + 1
        score_value = (row["score"] or {}).get("score", 0)
        if score_value < 25:
            buckets["0-25"] += 1
        elif score_value < 50:
            buckets["25-50"] += 1
        elif score_value < 75:
            buckets["50-75"] += 1
        else:
            buckets["75-100"] += 1
        for code in (row["score"] or {}).get("rejection_codes", []):
            rejection_codes[code] = rejection_codes.get(code, 0) + 1

    rows.sort(key=lambda r: (r["score"] or {}).get("score", 0), reverse=True)
    top = [
        {
            "id": r["id"],
            "symbol": r["symbol"],
            "name": r["name"],
            "chain": r["chain"],
            "score": (r["score"] or {}).get("score", 0),
            "confidence": r["data_confidence"],
            "security": (r["security"] or {}).get("overall"),
            "liquidity_usd": r["liquidity_usd"],
            "pct_h1": r["pct_h1"],
            "signal": r["strategy_signal"],
        }
        for r in rows[:10]
    ]
    rejected = [r for r in rows if r["strategy_signal"] == "REJECT"][:10]
    avg_score = sum((r["score"] or {}).get("score", 0) for r in rows) / len(rows) if rows else 0.0

    since = utc_now() - timedelta(hours=24)
    decision_counts = dict(
        (
            await session.execute(
                select(StrategyDecision.action, func.count(StrategyDecision.id))
                .where(StrategyDecision.created_at >= since)
                .group_by(StrategyDecision.action)
            )
        ).all()
    )
    discovered_last_hour = int(
        (
            await session.execute(
                select(func.count(Token.id)).where(
                    Token.first_discovered_at >= utc_now() - timedelta(hours=1)
                )
            )
        ).scalar_one()
    )

    return {
        "window_hours": 6,
        "tokens_tracked": len(tokens),
        "discovered_last_hour": discovered_last_hour,
        "by_chain": by_chain,
        "security": security_counts,
        "score_buckets": buckets,
        "avg_score": round(avg_score, 2),
        "top_opportunities": top,
        "recent_rejected": [
            {
                "id": r["id"],
                "symbol": r["symbol"],
                "chain": r["chain"],
                "score": (r["score"] or {}).get("score", 0),
                "reason_codes": (r["score"] or {}).get("rejection_codes", [])[:4],
                "security": (r["security"] or {}).get("overall"),
            }
            for r in rejected
        ],
        "rejection_codes": dict(
            sorted(rejection_codes.items(), key=lambda item: item[1], reverse=True)[:10]
        ),
        "decisions_24h": {str(k): int(v) for k, v in decision_counts.items()},
        "watchlist_count": len(watchlist),
        "open_positions": len(positions),
        "as_of": utc_now().isoformat(),
    }


async def watchlist_ids(session: AsyncSession) -> Iterable[int]:
    return list((await session.execute(select(WatchlistEntry.token_id))).scalars().all())

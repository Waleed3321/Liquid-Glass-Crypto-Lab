"""Persistence helpers for market data (tokens, pairs, snapshots, scores)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.models import (
    MarketSnapshot,
    OpportunityScore,
    Pair,
    SecurityCheck,
    Token,
    WatchlistEntry,
)
from app.providers.base import MarketQuote, PoolDiscovery
from app.services.security import SecurityAssessment


def _dec(value: float | int | str | None) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _volume_values(volume: dict[str, float] | None) -> dict[str, float]:
    data = volume or {}
    return {key: float(data.get(key, 0) or 0) for key in ("m5", "h1", "h6", "h24")}


def _txn_value(txns: dict[str, Any] | None, window: str, side: str) -> int:
    node = (txns or {}).get(window) or {}
    try:
        return int(node.get(side, 0) or 0)
    except (TypeError, ValueError):
        return 0


class TokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads -------------------------------------------------------------
    async def get(self, token_id: int) -> Token | None:
        return await self.session.get(Token, token_id)

    async def get_many(self, token_ids: Sequence[int]) -> list[Token]:
        if not token_ids:
            return []
        return list(
            (
                await self.session.execute(select(Token).where(Token.id.in_(token_ids)))
            ).scalars()
        )

    async def get_by_address(self, chain: str, address: str) -> Token | None:
        return (
            await self.session.execute(
                select(Token).where(Token.chain == chain, Token.address == address)
            )
        ).scalar_one_or_none()

    async def primary_pair(self, token_id: int) -> Pair | None:
        return (
            await self.session.execute(
                select(Pair)
                .where(Pair.token_id == token_id)
                .order_by(Pair.liquidity_usd.desc(), Pair.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def tokens_by_addresses(
        self, keys: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], Token]:
        wanted = set(keys)
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(Token).where(tuple_(Token.chain, Token.address).in_(sorted(wanted)))
            )
        ).scalars()
        return {(row.chain, row.address): row for row in rows}

    async def pairs_by_addresses(
        self, keys: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], Pair]:
        wanted = set(keys)
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(Pair).where(tuple_(Pair.chain, Pair.pair_address).in_(sorted(wanted)))
            )
        ).scalars()
        return {(row.chain, row.pair_address): row for row in rows}

    async def primary_pairs(self, token_ids: Sequence[int]) -> dict[int, Pair]:
        """Most liquid pair per token in one round trip (avoids per-token queries)."""
        if not token_ids:
            return {}
        ranked = (
            select(
                Pair.id.label("pair_id"),
                func.row_number()
                .over(
                    partition_by=Pair.token_id,
                    order_by=[Pair.liquidity_usd.desc(), Pair.id.asc()],
                )
                .label("rn"),
            )
            .where(Pair.token_id.in_(token_ids))
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(Pair).join(ranked, Pair.id == ranked.c.pair_id).where(ranked.c.rn == 1)
            )
        ).scalars()
        return {row.token_id: row for row in rows}

    async def latest_snapshot(self, pair_id: int) -> MarketSnapshot | None:
        return (
            await self.session.execute(
                select(MarketSnapshot)
                .where(MarketSnapshot.pair_id == pair_id)
                .order_by(MarketSnapshot.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def snapshots(
        self, token_id: int, *, since: datetime | None = None, limit: int = 200
    ) -> list[MarketSnapshot]:
        query = select(MarketSnapshot).where(MarketSnapshot.token_id == token_id)
        if since is not None:
            query = query.where(MarketSnapshot.ts >= since)
        query = query.order_by(MarketSnapshot.ts.asc()).limit(limit)
        return list((await self.session.execute(query)).scalars().all())

    async def snapshots_for_pair(
        self, pair_id: int, *, since: datetime | None = None, limit: int = 240
    ) -> list[MarketSnapshot]:
        query = select(MarketSnapshot).where(MarketSnapshot.pair_id == pair_id)
        if since is not None:
            query = query.where(MarketSnapshot.ts >= since)
        query = query.order_by(MarketSnapshot.ts.asc()).limit(limit)
        return list((await self.session.execute(query)).scalars().all())

    async def top_liquidity_tokens(
        self, *, window_start: datetime, limit: int, exclude: set[int] | None = None
    ) -> list[Token]:
        liquidity = (
            select(Pair.token_id, func.max(Pair.liquidity_usd).label("liq"))
            .group_by(Pair.token_id)
            .subquery()
        )
        query = (
            select(Token)
            .join(liquidity, liquidity.c.token_id == Token.id)
            .where(
                Token.is_active.is_(True),
                Token.first_discovered_at >= window_start,
            )
            .order_by(liquidity.c.liq.desc())
            .limit(limit)
        )
        if exclude:
            query = query.where(Token.id.notin_(exclude))
        return list((await self.session.execute(query)).scalars().all())

    async def latest_snapshots(self, token_ids: Sequence[int]) -> dict[int, MarketSnapshot]:
        if not token_ids:
            return {}
        sub = (
            select(MarketSnapshot.token_id, func.max(MarketSnapshot.ts).label("max_ts"))
            .where(MarketSnapshot.token_id.in_(token_ids))
            .group_by(MarketSnapshot.token_id)
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(MarketSnapshot).join(
                    sub,
                    and_(
                        MarketSnapshot.token_id == sub.c.token_id,
                        MarketSnapshot.ts == sub.c.max_ts,
                    ),
                )
            )
        ).scalars()
        return {row.token_id: row for row in rows}

    async def latest_scores(self, token_ids: Sequence[int]) -> dict[int, OpportunityScore]:
        if not token_ids:
            return {}
        sub = (
            select(OpportunityScore.token_id, func.max(OpportunityScore.ts).label("max_ts"))
            .where(OpportunityScore.token_id.in_(token_ids))
            .group_by(OpportunityScore.token_id)
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(OpportunityScore).join(
                    sub,
                    and_(
                        OpportunityScore.token_id == sub.c.token_id,
                        OpportunityScore.ts == sub.c.max_ts,
                    ),
                )
            )
        ).scalars()
        return {row.token_id: row for row in rows}

    async def latest_security(self, token_ids: Sequence[int]) -> dict[int, SecurityCheck]:
        if not token_ids:
            return {}
        sub = (
            select(SecurityCheck.token_id, func.max(SecurityCheck.ts).label("max_ts"))
            .where(SecurityCheck.token_id.in_(token_ids))
            .group_by(SecurityCheck.token_id)
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(SecurityCheck).join(
                    sub,
                    and_(
                        SecurityCheck.token_id == sub.c.token_id,
                        SecurityCheck.ts == sub.c.max_ts,
                    ),
                )
            )
        ).scalars()
        return {row.token_id: row for row in rows}

    async def active_tokens(self, *, window_start: datetime, limit: int = 400) -> list[Token]:
        query = (
            select(Token)
            .where(
                Token.is_active.is_(True),
                or_(
                    Token.first_discovered_at >= window_start,
                    Token.pair_created_at >= window_start,
                ),
            )
            .order_by(Token.first_discovered_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(query)).scalars().all())

    async def stale_candidates(
        self, *, window_start: datetime, checked_before: datetime, limit: int
    ) -> list[Token]:
        """Tokens inside the discovery window ordered by how long since analysis."""
        last_score = (
            select(OpportunityScore.token_id, func.max(OpportunityScore.ts).label("ts"))
            .group_by(OpportunityScore.token_id)
            .subquery()
        )
        query = (
            select(Token)
            .outerjoin(last_score, last_score.c.token_id == Token.id)
            .where(
                Token.is_active.is_(True),
                Token.first_discovered_at >= window_start,
                or_(last_score.c.ts.is_(None), last_score.c.ts < checked_before),
            )
            .order_by(func.coalesce(last_score.c.ts, Token.first_discovered_at).asc())
            .limit(limit)
        )
        return list((await self.session.execute(query)).scalars().all())

    # -- writes ------------------------------------------------------------
    async def upsert_discovery(
        self,
        discovery: PoolDiscovery,
        *,
        seen_at: datetime | None = None,
        token: Token | None = None,
        pair: Pair | None = None,
    ) -> tuple[Token, Pair]:
        """Persist a discovery, optionally reusing rows prefetched by the caller."""
        seen_at = seen_at or utc_now()
        if token is None:
            token = await self.get_by_address(discovery.chain, discovery.token_address)
        if token is None:
            token = Token(
                chain=discovery.chain,
                address=discovery.token_address,
                symbol=discovery.symbol or "?",
                name=discovery.name or discovery.symbol or "Unknown token",
                pair_created_at=discovery.created_at,
                first_discovered_at=seen_at,
                last_seen_at=seen_at,
                source=discovery.source,
            )
            self.session.add(token)
            await self.session.flush()
        else:
            token.last_seen_at = seen_at
            if not token.pair_created_at and discovery.created_at:
                token.pair_created_at = discovery.created_at
            if discovery.symbol and token.symbol in {"", "?"}:
                token.symbol = discovery.symbol
            if discovery.name and token.name in {"", "Unknown token"}:
                token.name = discovery.name
            token.is_active = True

        pair = await self._upsert_pair(token, discovery, pair=pair)
        return token, pair

    async def apply_quote(self, token: Token, quote: MarketQuote, *, seen_at: datetime | None = None) -> Pair:
        seen_at = seen_at or utc_now()
        token.last_seen_at = seen_at
        if not token.pair_created_at and quote.created_at:
            token.pair_created_at = quote.created_at
        same_token = quote.token_address.lower() == token.address.lower()
        if quote.symbol and (same_token or not token.symbol or token.symbol == "?"):
            token.symbol = quote.symbol
        if quote.name and (same_token or not token.name or token.name == "Unknown token"):
            token.name = quote.name
        if quote.image_url:
            token.image_url = quote.image_url
        if quote.website_url:
            token.website_url = quote.website_url
        pair = await self._upsert_pair(token, quote)
        return pair

    async def _upsert_pair(
        self,
        token: Token,
        data: PoolDiscovery | MarketQuote,
        *,
        pair: Pair | None = None,
    ) -> Pair:
        if pair is None:
            pair = (
                await self.session.execute(
                    select(Pair).where(
                        Pair.chain == token.chain, Pair.pair_address == data.pool_address
                    )
                )
            ).scalar_one_or_none()
        volume = _volume_values(data.volume)
        now = utc_now()
        if pair is None:
            pair = Pair(
                token_id=token.id,
                chain=token.chain,
                pair_address=data.pool_address,
                dex_id=data.dex_id,
                quote_symbol=data.quote_symbol,
                base_symbol=data.symbol,
            )
            self.session.add(pair)
        pair.price_usd = _dec(data.price_usd)
        pair.liquidity_usd = _dec(data.liquidity_usd)
        pair.market_cap_usd = _dec(data.market_cap_usd)
        pair.fdv_usd = _dec(data.fdv_usd)
        pair.volume = volume
        pair.txns = data.txns or {}
        pair.price_change = data.price_change or {}
        pair.last_updated_at = now
        pair.is_active = True
        # No flush here: the scanner updates many pairs per tick and lets the
        # session commit batch them into one round trip.
        return pair

    async def add_snapshot(
        self,
        token: Token,
        pair: Pair,
        *,
        ts: datetime | None = None,
        run_id: int | None = None,
        source: str = "dexscreener",
    ) -> MarketSnapshot:
        ts = ts or utc_now()
        volume = _volume_values(pair.volume)
        txns = pair.txns or {}
        changes = pair.price_change or {}
        snapshot = MarketSnapshot(
            token_id=token.id,
            pair_id=pair.id,
            ts=ts,
            price_usd=pair.price_usd,
            liquidity_usd=pair.liquidity_usd,
            market_cap_usd=pair.market_cap_usd,
            fdv_usd=pair.fdv_usd,
            volume_m5=_dec(volume.get("m5")),
            volume_h1=_dec(volume.get("h1")),
            volume_h6=_dec(volume.get("h6")),
            volume_h24=_dec(volume.get("h24")),
            buys_m5=_txn_value(txns, "m5", "buys"),
            sells_m5=_txn_value(txns, "m5", "sells"),
            buys_h1=_txn_value(txns, "h1", "buys"),
            sells_h1=_txn_value(txns, "h1", "sells"),
            pct_m5=float(changes.get("m5", 0) or 0),
            pct_h1=float(changes.get("h1", 0) or 0),
            pct_h6=float(changes.get("h6", 0) or 0),
            pct_h24=float(changes.get("h24", 0) or 0),
            txns=txns,
            volume=volume,
            source=source,
            scanner_run_id=run_id,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def store_security(
        self, token: Token, assessment: SecurityAssessment, *, ts: datetime | None = None
    ) -> SecurityCheck:
        check = SecurityCheck(
            token_id=token.id,
            chain=token.chain,
            ts=ts or utc_now(),
            provider="combined",
            overall=assessment.overall,
            risk_score=assessment.risk_score,
            critical_pass=assessment.critical_pass,
            critical_total=assessment.critical_total,
            fields=assessment.fields,
            reasons=assessment.reasons,
            raw=assessment.raw,
        )
        self.session.add(check)
        await self.session.flush()
        return check

    async def add_score(
        self,
        token: Token,
        pair: Pair | None,
        *,
        score: float,
        confidence: float,
        security_risk: float,
        signal_strength: float,
        rank_score: float,
        components: dict[str, Any],
        explanations: list[str],
        decision: str = "HOLD",
        rejection_codes: list[str] | None = None,
        ts: datetime | None = None,
    ) -> OpportunityScore:
        row = OpportunityScore(
            token_id=token.id,
            pair_id=pair.id if pair else None,
            ts=ts or utc_now(),
            score=score,
            confidence=confidence,
            security_risk=security_risk,
            signal_strength=signal_strength,
            rank_score=rank_score,
            components=components,
            explanations=explanations,
            decision=decision,
            rejection_codes=rejection_codes or [],
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # -- watchlist ---------------------------------------------------------
    async def watchlist_add(
        self, token_id: int, *, source: str = "user", note: str | None = None
    ) -> WatchlistEntry:
        existing = (
            await self.session.execute(
                select(WatchlistEntry).where(WatchlistEntry.token_id == token_id)
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        entry = WatchlistEntry(token_id=token_id, source=source, note=note)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def watchlist_remove(self, token_id: int) -> bool:
        result = await self.session.execute(
            delete(WatchlistEntry).where(WatchlistEntry.token_id == token_id)
        )
        return bool(result.rowcount)

    async def watchlist_token_ids(self) -> list[int]:
        return list(
            (await self.session.execute(select(WatchlistEntry.token_id))).scalars().all()
        )

    async def watchlist_rows(self) -> list[tuple[WatchlistEntry, Token, Pair | None]]:
        rows = await self.session.execute(
            select(WatchlistEntry, Token, Pair)
            .join(Token, Token.id == WatchlistEntry.token_id)
            .outerjoin(Pair, Pair.token_id == Token.id)
            .order_by(WatchlistEntry.added_at.desc())
        )
        return [(entry, token, pair) for entry, token, pair in rows.all()]

    # -- maintenance -------------------------------------------------------
    async def mark_inactive(self, token_ids: Iterable[int]) -> None:
        ids = list(token_ids)
        if not ids:
            return
        for token in (await self.session.execute(select(Token).where(Token.id.in_(ids)))).scalars():
            token.is_active = False

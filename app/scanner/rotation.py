"""Candidate rotation: open positions first, then watchlist, then liquid newcomers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Position, Token
from app.repositories.tokens import TokenRepository
from app.repositories.trading import TradingRepository


async def select_candidates(
    session: AsyncSession,
    *,
    window_start: datetime,
    limit: int,
) -> tuple[list[Token], list[Position]]:
    tokens = TokenRepository(session)
    trading = TradingRepository(session)

    positions = await trading.all_open_positions()
    selected: list[Token] = []
    seen: set[int] = set()

    async def add(token: Token | None) -> None:
        if token is None or token.id in seen:
            return
        seen.add(token.id)
        selected.append(token)

    for position in positions:
        await add(await tokens.get(position.token_id))
    for token_id in await tokens.watchlist_token_ids():
        await add(await tokens.get(token_id))
    for token in await tokens.top_liquidity_tokens(
        window_start=window_start, limit=max(limit * 2, limit), exclude=seen
    ):
        if len(selected) >= limit:
            break
        await add(token)

    return selected, positions

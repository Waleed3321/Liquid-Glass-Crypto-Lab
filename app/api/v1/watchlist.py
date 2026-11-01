"""Watchlist endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_hub, get_session_dep
from app.core.errors import NotFoundError
from app.repositories.tokens import TokenRepository
from app.schemas.watchlist import WatchlistIn
from app.services import market_service
from app.services.events import EventHub

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("")
async def get_watchlist(session: AsyncSession = Depends(get_session_dep)) -> dict:
    return await market_service.watchlist_view(session)


@router.post("", status_code=201)
async def add_watchlist(
    payload: WatchlistIn,
    session: AsyncSession = Depends(get_session_dep),
    hub: EventHub = Depends(get_hub),
) -> dict:
    repo = TokenRepository(session)
    token = await repo.get(payload.token_id)
    if token is None:
        raise NotFoundError("Token not found.")
    entry = await repo.watchlist_add(payload.token_id, note=payload.note)
    await session.commit()
    await hub.publish("watchlist", {"action": "added", "token_id": payload.token_id})
    return {
        "token_id": payload.token_id,
        "symbol": token.symbol,
        "watched": True,
        "added_at": entry.added_at.isoformat(),
    }


@router.delete("/{token_id}")
async def remove_watchlist(
    token_id: int,
    session: AsyncSession = Depends(get_session_dep),
    hub: EventHub = Depends(get_hub),
) -> dict:
    removed = await TokenRepository(session).watchlist_remove(token_id)
    await session.commit()
    await hub.publish("watchlist", {"action": "removed", "token_id": token_id})
    return {"token_id": token_id, "watched": False, "removed": removed}

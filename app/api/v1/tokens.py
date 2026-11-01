"""Token discovery, detail and history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_hub, get_session_dep
from app.core.errors import NotFoundError
from app.services import market_service
from app.services.events import EventHub

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.get("")
async def list_tokens(
    chain: str | None = None,
    search: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    security: str | None = None,
    signal: str | None = None,
    watchlist_only: bool = False,
    with_position: bool | None = None,
    window_hours: float | None = Query(default=None, gt=0, le=48),
    sort: str = "score",
    order: str = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    return await market_service.list_tokens(
        session,
        chain=chain,
        search=search,
        min_score=min_score,
        security=security,
        signal=signal,
        watchlist_only=watchlist_only,
        with_position=with_position,
        window_hours=window_hours,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/{token_id}")
async def token_detail(token_id: int, session: AsyncSession = Depends(get_session_dep)) -> dict:
    detail = await market_service.token_detail(session, token_id)
    if detail is None:
        raise NotFoundError("Token not found.")
    return detail


@router.get("/{token_id}/history")
async def token_history(
    token_id: int,
    hours: float = Query(default=6, gt=0, le=168),
    limit: int = Query(default=500, ge=10, le=2000),
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    history = await market_service.token_history(session, token_id, hours=hours, limit=limit)
    if history is None:
        raise NotFoundError("Token not found.")
    return history


@router.post("/{token_id}/watchlist")
async def add_watchlist(
    token_id: int,
    session: AsyncSession = Depends(get_session_dep),
    hub: EventHub = Depends(get_hub),
) -> dict:
    from app.repositories.tokens import TokenRepository

    repo = TokenRepository(session)
    token = await repo.get(token_id)
    if token is None:
        raise NotFoundError("Token not found.")
    entry = await repo.watchlist_add(token_id)
    await session.commit()
    await hub.publish("watchlist", {"action": "added", "token_id": token_id})
    return {"token_id": token_id, "watched": True, "added_at": entry.added_at.isoformat()}


@router.delete("/{token_id}/watchlist")
async def remove_watchlist(
    token_id: int,
    session: AsyncSession = Depends(get_session_dep),
    hub: EventHub = Depends(get_hub),
) -> dict:
    from app.repositories.tokens import TokenRepository

    removed = await TokenRepository(session).watchlist_remove(token_id)
    await session.commit()
    await hub.publish("watchlist", {"action": "removed", "token_id": token_id})
    return {"token_id": token_id, "watched": False, "removed": removed}

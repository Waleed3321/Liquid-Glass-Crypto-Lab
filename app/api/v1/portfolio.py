"""Paper portfolio endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_session_dep
from app.core.errors import NotFoundError
from app.repositories.tokens import TokenRepository
from app.repositories.trading import TradingRepository
from app.services import portfolio_service
from app.services.trade_read import position_dict

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("")
async def portfolio(session: AsyncSession = Depends(get_session_dep)) -> dict:
    summary = await portfolio_service.build_summary(session)
    return summary.as_dict()


@router.get("/positions")
async def positions(
    history: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    trading = TradingRepository(session)
    account = await trading.account()
    if account is None:
        raise NotFoundError("Paper account not found.")
    if history:
        rows = await trading.position_history(account.id, limit=limit, offset=offset)
    else:
        rows = await trading.open_positions(account.id)

    summary = await portfolio_service.build_summary(session)
    views = {view.id: view for view in summary.positions}
    tokens = TokenRepository(session)
    items = []
    for position in rows:
        view = views.get(position.id)
        if view is not None:
            items.append(view.as_dict())
            continue
        token = await tokens.get(position.token_id)
        items.append(position_dict(position, token))
    return {
        "total": len(items),
        "open_count": len(summary.positions),
        "limit": limit,
        "offset": offset,
        "positions": items,
        "estimated": True,
    }


@router.get("/performance")
async def performance(session: AsyncSession = Depends(get_session_dep)) -> dict:
    return await portfolio_service.performance_history(session)


@router.get("/equity")
async def equity(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    points = await portfolio_service.equity_series(session, days=days)
    return {"days": days, "points": points, "estimated": True}

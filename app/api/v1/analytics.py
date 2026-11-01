"""Market intelligence and portfolio analytics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_session_dep
from app.services import market_service, portfolio_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
async def analytics(
    include: str = "market,portfolio",
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    wanted = {part.strip() for part in include.split(",") if part.strip()}
    payload: dict = {}
    if "market" in wanted:
        payload["market"] = await market_service.analytics(session)
    if "portfolio" in wanted:
        summary = await portfolio_service.build_summary(session)
        performance = await portfolio_service.performance_history(session)
        payload["portfolio"] = {
            "summary": summary.as_dict(),
            "performance": performance,
            "equity": await portfolio_service.equity_series(session, days=30),
        }
    return payload


@router.get("/market")
async def market_analytics(session: AsyncSession = Depends(get_session_dep)) -> dict:
    return await market_service.analytics(session)


@router.get("/portfolio")
async def portfolio_analytics(session: AsyncSession = Depends(get_session_dep)) -> dict:
    summary = await portfolio_service.build_summary(session)
    return {
        "summary": summary.as_dict(),
        "performance": await portfolio_service.performance_history(session),
        "equity": await portfolio_service.equity_series(session, days=30),
    }

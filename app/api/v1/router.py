"""API v1 router assembly."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    health,
    notifications,
    portfolio,
    scanner,
    settings,
    strategies,
    tokens,
    trades,
    watchlist,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(scanner.router)
api_router.include_router(tokens.router)
api_router.include_router(watchlist.router)
api_router.include_router(portfolio.router)
api_router.include_router(trades.router)
api_router.include_router(strategies.router)
api_router.include_router(analytics.router)
api_router.include_router(notifications.router)
api_router.include_router(settings.router)

"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.notifications.dispatcher import NotificationDispatcher
from app.providers.registry import Providers
from app.scanner.runner import ScannerRunner
from app.services.events import EventHub


async def get_session_dep() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


def get_scanner(request: Request) -> ScannerRunner:
    return request.app.state.scanner


def get_providers(request: Request) -> Providers:
    return request.app.state.providers


def get_hub(request: Request) -> EventHub:
    return request.app.state.hub


def get_dispatcher(request: Request) -> NotificationDispatcher:
    return request.app.state.dispatcher

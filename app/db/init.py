"""Database bootstrap helpers.

Alembic owns schema evolution in production; ``create_all`` keeps local
development and tests frictionless.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_engine, session_scope
from app.models import AppSetting, PaperAccount

logger = logging.getLogger(__name__)

DEFAULT_ACCOUNT_NAME = "default"
ACCOUNT_KEY = "account.default"


async def create_all() -> None:
    import app.models  # noqa: F401  (ensure models are registered)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_schema_ready")


async def ensure_default_account() -> PaperAccount:
    """Create the $10 paper account on first boot without ever resetting it."""
    async with session_scope() as session:
        account = (
            await session.execute(
                select(PaperAccount).where(PaperAccount.name == DEFAULT_ACCOUNT_NAME)
            )
        ).scalar_one_or_none()
        if account is not None:
            return account

        initial = Decimal(str(settings.initial_balance_usd))
        account = PaperAccount(
            name=DEFAULT_ACCOUNT_NAME,
            initial_balance=initial,
            cash_balance=initial,
            realized_pnl=Decimal("0"),
        )
        session.add(account)
        await session.flush()

        existing = await session.get(AppSetting, ACCOUNT_KEY)
        if existing is None:
            session.add(AppSetting(key=ACCOUNT_KEY, value={"id": account.id}))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            account = (
                await session.execute(
                    select(PaperAccount).where(PaperAccount.name == DEFAULT_ACCOUNT_NAME)
                )
            ).scalar_one()
        logger.info("paper_account_ready", extra={"account_id": account.id})
        return account


async def init_database() -> None:
    await create_all()
    await ensure_default_account()

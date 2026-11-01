"""Persistence helpers for the paper-trading aggregates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyPerformance, Fill, Order, PaperAccount, Position
from app.models.enums import PositionStatus


class TradingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- account -----------------------------------------------------------
    async def account(self, *, name: str = "default", for_update: bool = False) -> PaperAccount | None:
        query = select(PaperAccount).where(PaperAccount.name == name)
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def account_by_id(self, account_id: int, *, for_update: bool = False) -> PaperAccount | None:
        query = select(PaperAccount).where(PaperAccount.id == account_id)
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    # -- positions ---------------------------------------------------------
    async def open_positions(self, account_id: int) -> list[Position]:
        return list(
            (
                await self.session.execute(
                    select(Position)
                    .where(
                        Position.account_id == account_id,
                        Position.status == PositionStatus.OPEN.value,
                    )
                    .order_by(Position.opened_at.desc())
                )
            )
            .scalars()
            .all()
        )

    async def open_position_count(self, account_id: int) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count(Position.id)).where(
                        Position.account_id == account_id,
                        Position.status == PositionStatus.OPEN.value,
                    )
                )
            ).scalar_one()
        )

    async def open_position_for_token(self, account_id: int, token_id: int) -> Position | None:
        return (
            await self.session.execute(
                select(Position).where(
                    Position.account_id == account_id,
                    Position.token_id == token_id,
                    Position.status == PositionStatus.OPEN.value,
                )
            )
        ).scalar_one_or_none()

    async def position(self, position_id: int, *, for_update: bool = False) -> Position | None:
        query = select(Position).where(Position.id == position_id)
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def all_open_positions(self) -> list[Position]:
        return list(
            (
                await self.session.execute(
                    select(Position).where(Position.status == PositionStatus.OPEN.value)
                )
            )
            .scalars()
            .all()
        )

    async def position_history(
        self, account_id: int, *, limit: int = 100, offset: int = 0
    ) -> list[Position]:
        return list(
            (
                await self.session.execute(
                    select(Position)
                    .where(Position.account_id == account_id)
                    .order_by(Position.opened_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )

    async def closed_positions(self, account_id: int) -> list[Position]:
        return list(
            (
                await self.session.execute(
                    select(Position)
                    .where(
                        Position.account_id == account_id,
                        Position.status == PositionStatus.CLOSED.value,
                    )
                    .order_by(Position.closed_at.asc())
                )
            )
            .scalars()
            .all()
        )

    # -- orders and fills --------------------------------------------------
    async def order_by_client_id(self, client_order_id: str) -> Order | None:
        return (
            await self.session.execute(
                select(Order).where(Order.client_order_id == client_order_id)
            )
        ).scalar_one_or_none()

    async def order_by_exit_key(self, exit_key: str) -> Order | None:
        return (
            await self.session.execute(select(Order).where(Order.exit_key == exit_key))
        ).scalar_one_or_none()

    async def fills_for_order(self, order_id: int) -> list[Fill]:
        return list(
            (await self.session.execute(select(Fill).where(Fill.order_id == order_id))).scalars().all()
        )

    async def recent_orders(self, account_id: int, *, limit: int = 100) -> list[Order]:
        return list(
            (
                await self.session.execute(
                    select(Order)
                    .where(Order.account_id == account_id)
                    .order_by(Order.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def recent_fills(self, account_id: int, *, limit: int = 100) -> list[Fill]:
        return list(
            (
                await self.session.execute(
                    select(Fill)
                    .where(Fill.account_id == account_id)
                    .order_by(Fill.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def fills_since(self, account_id: int, since: datetime) -> list[Fill]:
        return list(
            (
                await self.session.execute(
                    select(Fill)
                    .where(Fill.account_id == account_id, Fill.created_at >= since)
                    .order_by(Fill.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    # -- daily performance -------------------------------------------------
    async def daily(
        self, account_id: int, day: date, *, for_update: bool = False
    ) -> DailyPerformance | None:
        query = select(DailyPerformance).where(
            DailyPerformance.account_id == account_id, DailyPerformance.day == day
        )
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def ensure_daily(
        self, account_id: int, day: date, starting_equity: Decimal | None = None
    ) -> DailyPerformance:
        row = await self.daily(account_id, day)
        if row is None:
            row = DailyPerformance(
                account_id=account_id,
                day=day,
                starting_equity=starting_equity or Decimal("0"),
                ending_equity=starting_equity or Decimal("0"),
            )
            self.session.add(row)
            await self.session.flush()
        return row

    async def daily_history(self, account_id: int, *, limit: int = 60) -> list[DailyPerformance]:
        return list(
            (
                await self.session.execute(
                    select(DailyPerformance)
                    .where(DailyPerformance.account_id == account_id)
                    .order_by(DailyPerformance.day.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def oldest_open_position(self, account_id: int) -> Position | None:
        return (
            await self.session.execute(
                select(Position)
                .where(
                    Position.account_id == account_id,
                    Position.status == PositionStatus.OPEN.value,
                )
                .order_by(Position.opened_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def last_exit_time(self, account_id: int, token_id: int) -> datetime | None:
        return (
            await self.session.execute(
                select(func.max(Position.closed_at)).where(
                    Position.account_id == account_id,
                    Position.token_id == token_id,
                    Position.status == PositionStatus.CLOSED.value,
                )
            )
        ).scalar_one_or_none()

    async def positions_for_tokens(self, account_id: int, token_ids: Sequence[int]) -> list[Position]:
        if not token_ids:
            return []
        return list(
            (
                await self.session.execute(
                    select(Position).where(
                        Position.account_id == account_id,
                        Position.token_id.in_(token_ids),
                    )
                )
            )
            .scalars()
            .all()
        )

"""Paper trade execution and history endpoints.

Every limit is enforced inside :mod:`app.services.trade_service`, never here.
Manual and automatic (scanner) trades share the exact same code path.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_hub, get_session_dep
from app.core.errors import NotFoundError, ValidationError
from app.models import Token
from app.repositories.trading import TradingRepository
from app.schemas.trades import BuyRequestIn, SellRequestIn
from app.services import trade_service
from app.services.events import EventHub
from app.services.trade_read import fill_dict, order_dict, position_dict

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])


async def _token_index(session: AsyncSession, ids: set[int]) -> dict[int, Token]:
    if not ids:
        return {}
    rows = (await session.execute(select(Token).where(Token.id.in_(ids)))).scalars().all()
    return {token.id: token for token in rows}


@router.post("/buy")
async def paper_buy(
    payload: BuyRequestIn,
    hub: EventHub = Depends(get_hub),
) -> dict:
    outcome = await trade_service.execute_buy(
        trade_service.BuyRequest(
            token_id=payload.token_id,
            notional_usd=payload.notional_usd,
            client_order_id=payload.client_order_id,
            source="manual",
            reason="Manual paper buy",
        )
    )
    await hub.publish(
        "trade",
        {
            "side": "BUY",
            "duplicate": outcome.duplicate,
            "position_id": outcome.position.id if outcome.position else None,
            "fill_price": float(outcome.fill.price) if outcome.fill else None,
            "cash_balance": outcome.cash_balance,
        },
    )
    return {
        "duplicate": outcome.duplicate,
        "order_id": outcome.order.id,
        "position_id": outcome.position.id if outcome.position else None,
        "token_id": payload.token_id,
        "side": outcome.order.side,
        "status": outcome.order.status,
        "qty": float(outcome.order.qty),
        "fill_price": float(outcome.order.fill_price) if outcome.order.fill_price else None,
        "fill_notional": float(outcome.order.fill_notional) if outcome.order.fill_notional else None,
        "fees": (
            {
                "network": float(outcome.fill.fee_network),
                "dex": float(outcome.fill.fee_dex),
                "tax": float(outcome.fill.fee_tax),
                "total": float(
                    outcome.fill.fee_network + outcome.fill.fee_dex + outcome.fill.fee_tax
                ),
            }
            if outcome.fill
            else None
        ),
        "slippage_pct": float(outcome.fill.slippage_pct) if outcome.fill else None,
        "impact_pct": float(outcome.fill.impact_pct) if outcome.fill else None,
        "cash_balance": outcome.cash_balance,
        "security": outcome.assessment.summary() if outcome.assessment else None,
        "estimated": True,
    }


@router.post("/sell")
async def paper_sell(
    payload: SellRequestIn,
    hub: EventHub = Depends(get_hub),
) -> dict:
    if payload.ratio is not None and payload.qty is not None:
        raise ValidationError("Provide either ratio or qty, not both.")
    outcome = await trade_service.execute_sell(
        trade_service.SellRequest(
            position_id=payload.position_id,
            ratio=payload.ratio,
            qty=payload.qty,
            reason="Manual paper sell",
            exit_key=payload.exit_key,
            source="manual",
        )
    )
    await hub.publish(
        "trade",
        {
            "side": "SELL",
            "duplicate": outcome.duplicate,
            "position_id": outcome.position.id,
            "realized_pnl": outcome.realized_pnl,
            "status": outcome.position.status,
        },
    )
    return {
        "duplicate": outcome.duplicate,
        "order_id": outcome.order.id,
        "position_id": outcome.position.id,
        "status": outcome.position.status,
        "remaining_qty": float(outcome.position.remaining_qty),
        "qty": float(outcome.order.qty),
        "fill_price": float(outcome.fill.price) if outcome.fill else None,
        "proceeds_usd": outcome.proceeds_usd,
        "realized_pnl": outcome.realized_pnl,
        "realized_pnl_total": float(outcome.position.realized_pnl),
        "exit_reason": outcome.position.exit_reason,
        "estimated": True,
    }


@router.get("/history")
async def paper_history(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session_dep),
) -> dict:
    trading = TradingRepository(session)
    account = await trading.account()
    if account is None:
        raise NotFoundError("Paper account not found.")

    orders = await trading.recent_orders(account.id, limit=limit)
    fills = await trading.recent_fills(account.id, limit=limit)
    positions = await trading.position_history(account.id, limit=limit, offset=offset)
    ids = {order.token_id for order in orders if order.token_id}
    ids |= {position.token_id for position in positions}
    tokens = await _token_index(session, ids)
    order_tokens = {order.id: order.token_id for order in orders}
    position_tokens = {position.id: position.token_id for position in positions}

    def token_for_fill(fill) -> Token | None:
        token_id = order_tokens.get(fill.order_id) or position_tokens.get(fill.position_id or 0)
        return tokens.get(token_id) if token_id else None

    return {
        "limit": limit,
        "offset": offset,
        "orders": [order_dict(order, tokens.get(order.token_id)) for order in orders],
        "fills": [fill_dict(fill, token_for_fill(fill)) for fill in fills],
        "positions": [position_dict(pos, tokens.get(pos.token_id)) for pos in positions],
        "estimated": True,
    }

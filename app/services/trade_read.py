"""Serialisers shared by the trading routes and the SSE stream."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from app.models import Fill, Order, Position, Token


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def order_dict(order: Order, token: Token | None = None) -> dict[str, Any]:
    return {
        "id": order.id,
        "token_id": order.token_id,
        "position_id": order.position_id,
        "symbol": token.symbol if token else None,
        "chain": token.chain if token else None,
        "side": order.side,
        "status": order.status,
        "client_order_id": order.client_order_id,
        "exit_key": order.exit_key,
        "requested_notional": _f(order.requested_notional),
        "qty": _f(order.qty),
        "fill_price": _f(order.fill_price) if order.fill_price is not None else None,
        "fill_notional": _f(order.fill_notional) if order.fill_notional is not None else None,
        "reject_code": order.reject_code,
        "reason": order.reason,
        "source": order.source,
        "created_at": _iso(order.created_at),
        "filled_at": _iso(order.filled_at),
        "meta": order.meta or {},
        "estimated": True,
    }


def fill_dict(fill: Fill, token: Token | None = None) -> dict[str, Any]:
    return {
        "id": fill.id,
        "order_id": fill.order_id,
        "position_id": fill.position_id,
        "symbol": token.symbol if token else None,
        "chain": token.chain if token else None,
        "side": fill.sector,
        "price": _f(fill.price),
        "qty": _f(fill.qty),
        "notional": _f(fill.notional),
        "fee_network": _f(fill.fee_network),
        "fee_dex": _f(fill.fee_dex),
        "fee_tax": _f(fill.fee_tax),
        "fee_total": _f(fill.fee_network) + _f(fill.fee_dex) + _f(fill.fee_tax),
        "slippage_pct": _f(fill.slippage_pct),
        "impact_pct": _f(fill.impact_pct),
        "realized_pnl": _f(fill.realized_pnl),
        "price_source_ts": _iso(fill.price_source_ts),
        "is_estimate": fill.is_estimate,
        "created_at": _iso(fill.created_at),
    }


def position_dict(position: Position, token: Token | None = None) -> dict[str, Any]:
    return {
        "id": position.id,
        "token_id": position.token_id,
        "symbol": token.symbol if token else "",
        "name": token.name if token else "",
        "chain": token.chain if token else "",
        "address": token.address if token else "",
        "status": position.status,
        "qty": _f(position.qty),
        "remaining_qty": _f(position.remaining_qty),
        "entry_price": _f(position.entry_price),
        "entry_notional": _f(position.entry_notional),
        "entry_fees": _f(position.entry_fees),
        "invested_usd": _f(position.invested_usd),
        "realized_pnl": _f(position.realized_pnl),
        "fees_paid": _f(position.fees_paid),
        "peak_price": _f(position.peak_price),
        "trail_high": _f(position.trail_high),
        "stop_price": _f(position.stop_price) if position.stop_price is not None else None,
        "protection_armed": position.protection_armed,
        "opened_at": _iso(position.opened_at),
        "closed_at": _iso(position.closed_at),
        "exit_reason": position.exit_reason,
        "strategy_version": position.strategy_version,
        "entry_liquidity_usd": _f(position.entry_liquidity_usd),
        "estimated": True,
    }


def token_map(tokens: Iterable[Token]) -> dict[int, Token]:
    return {token.id: token for token in tokens}


def symbol_map(tokens: Sequence[Token]) -> dict[int, str]:
    return {token.id: token.symbol for token in tokens}

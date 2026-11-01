"""Convert stored notifications into Discord-ready messages."""

from __future__ import annotations

from app.models import Notification
from app.providers.base import NotificationMessage


def _fmt_money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_price(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if number == 0:
        return "$0"
    if number < 0.0001:
        return f"${number:.10f}"
    if number < 1:
        return f"${number:.6f}"
    return f"${number:,.4f}"


def to_message(notification: Notification) -> NotificationMessage:
    payload = notification.payload or {}
    fields: list[tuple[str, str]] = []
    if payload.get("chain"):
        chain = payload["chain"]
        fields.append(("Chain", {"solana": "Solana", "bsc": "BNB Chain"}.get(chain, chain)))
    if payload.get("symbol"):
        fields.append(("Token", f"{payload.get('name') or ''} ({payload['symbol']})".strip()))
    if payload.get("address"):
        fields.append(("Contract", str(payload["address"])))
    if payload.get("price") is not None:
        fields.append(("Price", _fmt_price(payload["price"])))
    if payload.get("score") is not None:
        fields.append(("Score", f"{float(payload['score']):.1f}/100"))
    if payload.get("security"):
        fields.append(("Security", str(payload["security"])))
    if payload.get("notional") is not None:
        fields.append(("Paper size", _fmt_money(payload["notional"])))
    if payload.get("realized_pnl") is not None:
        value = float(payload["realized_pnl"])
        fields.append(("P&L", f"{value:+.2f} USD"))
    if payload.get("reason"):
        fields.append(("Reason", str(payload["reason"])))
    if payload.get("impact_pct") is not None:
        fields.append(("Est. impact", f"{float(payload['impact_pct']):.3f}%"))
    if payload.get("slippage_pct") is not None:
        fields.append(("Est. slippage", f"{float(payload['slippage_pct']):.3f}%"))

    return NotificationMessage(
        title=notification.title,
        body=notification.message,
        severity=notification.severity,
        fields=fields,
        url=None,
    )

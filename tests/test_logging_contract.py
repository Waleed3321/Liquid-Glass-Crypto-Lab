"""Structured-logging contract: stdlib loggers reject arbitrary kwargs.

A bare ``logger.info("event", token_id=...)`` raises ``TypeError`` at emit
time, which used to roll back real paper fills. These tests guard both the
convention and the two trading paths that hit it.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from app.services import trade_service

APP_DIR = Path(__file__).resolve().parents[1] / "app"
ALLOWED_KWARGS = {"extra", "exc_info", "stack_info", "stacklevel"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def test_no_logger_calls_with_invalid_kwargs():
    offenders: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in LOG_METHODS:
                continue
            base = node.func.value
            if not (isinstance(base, ast.Name) and base.id == "logger"):
                continue
            bad = [kw.arg for kw in node.keywords if kw.arg and kw.arg not in ALLOWED_KWARGS]
            if bad:
                offenders.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno} {bad}")
    assert offenders == []


async def test_buy_and_sell_log_at_info_without_raising(seed, caplog):
    caplog.set_level(logging.INFO, logger="app.services.trade_service")
    token_id = await seed()

    bought = await trade_service.execute_buy(
        trade_service.BuyRequest(token_id=token_id, notional_usd=2.5)
    )
    sold = await trade_service.execute_sell(
        trade_service.SellRequest(
            position_id=bought.position.id, ratio=1.0, exit_key="log-contract-exit"
        )
    )

    assert sold.order.status == "FILLED"
    messages = [record.getMessage() for record in caplog.records]
    assert "paper_buy_filled" in messages
    assert "paper_sell_filled" in messages

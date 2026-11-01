"""Risk enforcement and paper-trading lifecycle tests (the 20 required cases)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.clock import utc_now
from app.core.errors import RiskLimitError
from app.db.session import dispose_engine, session_scope
from app.models import DailyPerformance, Fill, Order, PaperAccount, Position
from app.services import trade_service
from app.services.portfolio_service import build_summary
from tests.helpers import add_snapshot, set_today_daily


async def _buy(token_id: int, notional: float | None = 2.5, client_id: str | None = None):
    return await trade_service.execute_buy(
        trade_service.BuyRequest(
            token_id=token_id, notional_usd=notional, client_order_id=client_id
        )
    )


async def _sell(position_id: int, ratio: float | None = 1.0, exit_key: str | None = None,
                reason: str = "Manual paper sell"):
    return await trade_service.execute_sell(
        trade_service.SellRequest(
            position_id=position_id, ratio=ratio, exit_key=exit_key, reason=reason
        )
    )


async def _account_row() -> PaperAccount:
    async with session_scope() as session:
        return (
            await session.execute(select(PaperAccount).where(PaperAccount.name == "default"))
        ).scalar_one()


# 1 ---------------------------------------------------------------------------
async def test_fresh_account_starts_with_exactly_ten_dollars(account):
    assert float(account.initial_balance) == 10.0
    assert float(account.cash_balance) == 10.0
    assert float(account.realized_pnl) == 0.0
    assert account.is_halted is False


# 2 ---------------------------------------------------------------------------
async def test_buy_records_position_cash_and_estimated_fees(seed):
    token_id = await seed()
    outcome = await _buy(token_id)

    position = outcome.position
    fill = outcome.fill
    assert position is not None and fill is not None
    assert outcome.order.status == "FILLED"
    assert float(position.entry_notional) == pytest.approx(2.5)
    assert float(position.remaining_qty) == pytest.approx(float(position.qty))
    assert outcome.cash_balance == pytest.approx(10.0 - float(position.entry_cost))
    assert fill.is_estimate is True
    assert float(fill.fee_network) > 0
    assert float(fill.fee_dex) == pytest.approx(2.5 * 0.0025, rel=1e-6)
    assert float(fill.slippage_pct) >= 0.5
    assert 0.0 < float(fill.impact_pct) < 1.0
    assert fill.price_source_ts is not None

    fresh = await _account_row()
    assert float(fresh.cash_balance) == pytest.approx(outcome.cash_balance)


async def test_default_order_size_caps_at_two_fifty(seed):
    token_id = await seed()
    outcome = await _buy(token_id, notional=None)
    assert float(outcome.position.entry_notional) == pytest.approx(2.5)


# 3 / 4 -----------------------------------------------------------------------
async def test_fourth_open_position_is_rejected(seed):
    tokens = [await seed(symbol=f"MAX{i}") for i in range(4)]
    for token_id in tokens[:3]:
        await _buy(token_id)

    with pytest.raises(RiskLimitError) as exc:
        await _buy(tokens[3], notional=2.0)
    assert exc.value.code == "MAX_POSITIONS"


async def test_position_above_two_fifty_is_rejected(seed):
    token_id = await seed()
    with pytest.raises(RiskLimitError) as exc:
        await _buy(token_id, notional=3.0)
    assert exc.value.code == "POSITION_SIZE"


async def test_insufficient_cash_is_rejected(seed):
    token_id = await seed()
    async with session_scope() as session:
        account = (
            await session.execute(select(PaperAccount).where(PaperAccount.name == "default"))
        ).scalar_one()
        account.cash_balance = Decimal("1.00")
    with pytest.raises(RiskLimitError) as exc:
        await _buy(token_id, notional=2.5)
    assert exc.value.code == "INSUFFICIENT_BALANCE"


# 5 ---------------------------------------------------------------------------
async def test_daily_loss_limit_blocks_entries_and_rolls_over(seed):
    loser = await seed(symbol="LOSS")
    outcome = await _buy(loser)
    async with session_scope() as session:
        await add_snapshot(session, loser, price=0.0006)
    sold = await _sell(outcome.position.id, ratio=1.0, reason="STOP_LOSS")
    assert sold.realized_pnl <= -0.5

    async with session_scope() as session:
        account = (
            await session.execute(select(PaperAccount).where(PaperAccount.name == "default"))
        ).scalar_one()
        daily = (
            await session.execute(select(DailyPerformance))
        ).scalars().one()
    assert account.is_halted is True
    assert daily.halted is True
    assert daily.realized_pnl <= Decimal("-0.5")

    winner = await seed(symbol="NEXT")
    with pytest.raises(RiskLimitError) as exc:
        await _buy(winner)
    assert exc.value.code == "DAILY_LOSS_LIMIT"

    # Next trading day: the halted row belongs to yesterday, so entries resume.
    async with session_scope() as session:
        row = (await session.execute(select(DailyPerformance))).scalars().one()
        row.day = row.day - timedelta(days=1)
    resumed = await _buy(winner)
    assert resumed.position is not None
    async with session_scope() as session:
        fresh_daily = (
            await session.execute(
                select(DailyPerformance).where(DailyPerformance.day == utc_now().date())
            )
        ).scalar_one()
    assert fresh_daily.realized_pnl == Decimal("0")
    assert fresh_daily.halted is False


# 6 ---------------------------------------------------------------------------
async def test_token_tax_is_charged_on_entry(seed):
    token_id = await seed(
        field_overrides={"buy_tax": {"status": "PASS", "value": 2.0}, "sell_tax": {"status": "PASS", "value": 2.0}}
    )
    outcome = await _buy(token_id)
    fill = outcome.fill
    assert fill is not None
    assert float(fill.fee_tax) == pytest.approx(2.5 * 0.02, rel=1e-6)
    assert float(outcome.position.qty) < 2.5 / float(outcome.position.entry_price)


# 7 ---------------------------------------------------------------------------
async def test_partial_exit_sells_exactly_half(seed):
    token_id = await seed()
    bought = await _buy(token_id)
    original = Decimal(str(bought.position.remaining_qty))
    async with session_scope() as session:
        await add_snapshot(session, token_id, price=0.0016)

    sold = await _sell(bought.position.id, ratio=0.5, exit_key="take_profit_half")
    assert sold.duplicate is False
    assert sold.position.status == "OPEN"
    assert float(sold.position.remaining_qty) == pytest.approx(float(original) / 2.0, rel=1e-6)


async def test_full_exit_closes_position(seed):
    token_id = await seed()
    bought = await _buy(token_id)
    async with session_scope() as session:
        await add_snapshot(session, token_id, price=0.0018)

    sold = await _sell(bought.position.id, ratio=1.0, exit_key="take_profit_full")
    assert sold.position.status == "CLOSED"
    assert float(sold.position.remaining_qty) == 0.0
    assert sold.position.closed_at is not None
    assert sold.position.exit_reason == "Manual paper sell"
    assert sold.realized_pnl > 0


async def test_realized_and_unrealized_pnl_are_tracked(seed):
    token_id = await seed()
    bought = await _buy(token_id)
    async with session_scope() as session:
        await add_snapshot(session, token_id, price=0.0012)
        summary = await build_summary(session)

    assert summary.open_positions == 1
    assert summary.unrealized_pnl > 0
    assert summary.equity > 9.9

    sold = await _sell(bought.position.id, ratio=1.0, exit_key="take_profit_full")
    async with session_scope() as session:
        closed_summary = await build_summary(session)
    assert closed_summary.open_positions == 0
    assert closed_summary.realized_pnl == pytest.approx(sold.realized_pnl, abs=1e-6)
    assert closed_summary.unrealized_pnl == pytest.approx(0.0, abs=1e-9)


# 8 ---------------------------------------------------------------------------
async def test_duplicate_buy_client_id_replays_without_double_spending(seed):
    token_id = await seed()
    first = await _buy(token_id, client_id="manual-duplicate-1")
    cash_after_first = first.cash_balance

    replay = await _buy(token_id, client_id="manual-duplicate-1")
    assert replay.duplicate is True
    assert replay.cash_balance == pytest.approx(cash_after_first)

    async with session_scope() as session:
        positions = (
            await session.execute(select(func.count(Position.id)))
        ).scalar_one()
        orders = (await session.execute(select(func.count(Order.id)))).scalar_one()
        fills = (await session.execute(select(func.count(Fill.id)))).scalar_one()
    assert (positions, orders, fills) == (1, 1, 1)


async def test_duplicate_exit_key_never_double_sells(seed):
    token_id = await seed()
    bought = await _buy(token_id)
    first = await _sell(bought.position.id, ratio=0.5, exit_key="pos:tp50")
    remaining = Decimal(str(first.position.remaining_qty))

    replay = await _sell(bought.position.id, ratio=0.5, exit_key="pos:tp50")
    assert replay.duplicate is True
    assert float(replay.position.remaining_qty) == pytest.approx(float(remaining), abs=1e-9)


async def test_position_exists_blocks_second_position_for_same_token(seed):
    token_id = await seed()
    await _buy(token_id)
    with pytest.raises(RiskLimitError) as exc:
        await _buy(token_id, notional=1.0)
    assert exc.value.code == "POSITION_EXISTS"


# 9 ---------------------------------------------------------------------------
async def test_stale_snapshot_rejects_entry(seed):
    token_id = await seed(snapshot_ts=utc_now() - timedelta(seconds=600))
    with pytest.raises(RiskLimitError) as exc:
        await _buy(token_id)
    assert exc.value.code == "STALE_DATA"


async def test_security_failure_rejects_entry(seed):
    token_id = await seed(
        security="FAIL",
        field_overrides={
            "honeypot": {"status": "FAIL", "value": True, "reason": "honeypot detected"}
        },
    )
    with pytest.raises(RiskLimitError) as exc:
        await _buy(token_id)
    assert exc.value.code == "SECURITY_REJECTED"


async def test_missing_security_data_blocks_entry(seed):
    token_id = await seed(security=None)
    with pytest.raises(RiskLimitError) as exc:
        await _buy(token_id)
    assert exc.value.code == "SECURITY_INCOMPLETE"


async def test_unknown_critical_field_blocks_entry(seed):
    token_id = await seed(
        security="UNKNOWN",
        field_overrides={
            "freezable": {"status": "UNKNOWN", "value": None, "reason": "no data"}
        },
    )
    with pytest.raises(RiskLimitError) as exc:
        await _buy(token_id)
    assert exc.value.code == "SECURITY_INCOMPLETE"


# 10 --------------------------------------------------------------------------
async def test_twenty_concurrent_buys_respect_position_cap_and_cash(seed):
    tokens = [await seed(symbol=f"CONC{i}") for i in range(6)]
    tasks = [
        _buy(tokens[index % len(tokens)], notional=2.5, client_id=f"conc-{index}")
        for index in range(20)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    successes = [result for result in results if not isinstance(result, BaseException)]

    async with session_scope() as session:
        open_count = (
            await session.execute(
                select(func.count(Position.id)).where(Position.status == "OPEN")
            )
        ).scalar_one()
        account = (
            await session.execute(select(PaperAccount).where(PaperAccount.name == "default"))
        ).scalar_one()
        entry_costs = [
            Decimal(str(row.entry_cost))
            for row in (await session.execute(select(Position))).scalars().all()
        ]

    assert open_count <= 3
    assert len(successes) == open_count
    assert Decimal(str(account.cash_balance)) >= 0
    assert float(account.cash_balance) == pytest.approx(
        10.0 - float(sum(entry_costs, Decimal("0"))), abs=1e-6
    )
    for result in results:
        if isinstance(result, BaseException):
            assert isinstance(result, RiskLimitError)


# 11 --------------------------------------------------------------------------
async def test_positions_and_cash_survive_engine_restart(seed):
    token_id = await seed()
    bought = await _buy(token_id)
    cash = bought.cash_balance
    position_id = bought.position.id

    await dispose_engine()

    async with session_scope() as session:
        position = await session.get(Position, position_id)
        account = (
            await session.execute(select(PaperAccount).where(PaperAccount.name == "default"))
        ).scalar_one()
        daily_rows = (await session.execute(select(DailyPerformance))).scalars().all()
    assert position is not None and position.status == "OPEN"
    assert float(account.cash_balance) == pytest.approx(cash)
    assert len(daily_rows) == 1
    assert daily_rows[0].entries == 1


# 32 --------------------------------------------------------------------------
async def test_buy_logs_at_info_without_raising(seed, caplog):
    """Regression: logging must never abort a committed paper fill."""
    import logging

    caplog.set_level(logging.INFO, logger="app.services.trade_service")
    token_id = await seed()
    outcome = await _buy(token_id)
    assert outcome.position is not None
    assert any("paper_buy_filled" in record.getMessage() for record in caplog.records)

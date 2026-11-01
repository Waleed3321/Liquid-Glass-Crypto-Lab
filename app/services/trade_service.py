"""Paper trading service: the only writer of positions, orders, fills and cash.

All entry points run inside :func:`app.risk.locks.risk_transaction`, which
serialises risk checks and keeps the account row locked for the whole operation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.clock import utc_now
from app.core.config import settings
from app.core.errors import (
    REASON_DUPLICATE_ORDER,
    REASON_NO_POSITION,
    REASON_QUANTITY,
    REASON_STALE_DATA,
    NotFoundError,
    RiskLimitError,
)
from app.core.logging import get_logger
from app.execution.quote import Quote, QuoteRequest, build_buy_quote
from app.execution.simulator import simulate_buy, simulate_sell
from app.models import Fill, Order, PaperAccount, Position
from app.models.enums import NotificationKind, OrderSide, OrderStatus, PositionStatus
from app.repositories.system import SystemRepository
from app.repositories.tokens import TokenRepository
from app.repositories.trading import TradingRepository
from app.risk.daily_loss import current_trading_day, loss_limit_reached
from app.risk.guards import (
    check_cash,
    check_daily_loss,
    check_open_slots,
    check_position_size,
    check_quote,
    check_security,
)
from app.risk.limits import RiskLimits
from app.risk.locks import risk_transaction
from app.services.security import SecurityAssessment, assessment_from_check
from app.services.settings_service import load_strategy_config

logger = get_logger(__name__)


def _dec(value: float | Decimal | None) -> Decimal:
    return Decimal(str(value or 0))


def _money(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.00000001")))


@dataclass(slots=True)
class BuyRequest:
    token_id: int
    notional_usd: float | None = None
    client_order_id: str | None = None
    source: str = "manual"
    reason: str = "Manual paper buy"


@dataclass(slots=True)
class BuyOutcome:
    order: Order
    position: Position | None
    fill: Fill | None
    quote: Quote | None
    assessment: SecurityAssessment | None
    duplicate: bool = False
    cash_balance: float = 0.0


@dataclass(slots=True)
class SellRequest:
    position_id: int
    ratio: float | None = None
    qty: float | None = None
    reason: str = "Manual paper sell"
    exit_key: str | None = None
    source: str = "manual"


@dataclass(slots=True)
class SellOutcome:
    order: Order
    position: Position
    fill: Fill | None
    duplicate: bool = False
    realized_pnl: float = 0.0
    proceeds_usd: float = 0.0


async def _recent_prices(tokens: TokenRepository, token_id: int, limit: int = 4) -> list[float]:
    rows = await tokens.snapshots(token_id, limit=200)
    prices = [float(row.price_usd) for row in rows[-limit:]]
    return prices


async def _current_equity(trading: TradingRepository, account: PaperAccount) -> Decimal:
    positions = await trading.open_positions(account.id)
    invested = sum((Decimal(str(p.invested_usd)) for p in positions), Decimal("0"))
    return Decimal(str(account.cash_balance)) + invested


async def execute_buy(request: BuyRequest, *, account_name: str = "default") -> BuyOutcome:
    async with risk_transaction(account_name=account_name) as (session, account):
        repo = TradingRepository(session)
        tokens = TokenRepository(session)
        system = SystemRepository(session)
        cfg = await load_strategy_config(session)
        limits = RiskLimits.from_config(cfg)

        client_id = request.client_order_id or f"{request.source}-{uuid.uuid4().hex[:24]}"
        existing = await repo.order_by_client_id(client_id)
        if existing is not None:
            fills = await repo.fills_for_order(existing.id)
            position = await repo.position(existing.position_id) if existing.position_id else None
            return BuyOutcome(
                order=existing,
                position=position,
                fill=fills[0] if fills else None,
                quote=None,
                assessment=None,
                duplicate=True,
                cash_balance=float(account.cash_balance),
            )

        token = await tokens.get(request.token_id)
        if token is None:
            raise NotFoundError("Token not found.")
        if not token.is_active:
            raise RiskLimitError("Token is no longer active on the scanner.", code=REASON_STALE_DATA)

        pair = await tokens.primary_pair(token.id)
        if pair is None:
            raise RiskLimitError("No tradable pair exists for this token.", code=REASON_STALE_DATA)
        snapshot = await tokens.latest_snapshot(pair.id)
        if snapshot is None:
            raise RiskLimitError("No market snapshot is available yet.", code=REASON_STALE_DATA)

        checks = await tokens.latest_security([token.id])
        check = checks.get(token.id)
        assessment = assessment_from_check(check) if check is not None else None
        check_security(assessment)
        assert assessment is not None

        cash = Decimal(str(account.cash_balance))
        requested = request.notional_usd
        if requested is None:
            requested = min(limits.max_position_usd, float(cash))
        requested = round(float(requested), 6)
        check_position_size(requested, limits)

        if await repo.open_position_for_token(account.id, token.id) is not None:
            raise RiskLimitError(
                "A paper position is already open for this token.", code="POSITION_EXISTS"
            )

        # A re-entry is allowed only after the cooldown window.
        last_exit = await repo.last_exit_time(account.id, token.id)
        if last_exit is not None:
            elapsed = (utc_now() - last_exit).total_seconds() / 60.0
            if elapsed < cfg.cooldown_after_exit_minutes:
                raise RiskLimitError(
                    f"Cooldown active: {cfg.cooldown_after_exit_minutes - int(elapsed)} minutes remain.",
                    code="COOLDOWN_ACTIVE",
                )

        recent = await _recent_prices(tokens, token.id)
        quote = build_buy_quote(
            QuoteRequest(
                chain=token.chain,
                notional_usd=requested,
                price_usd=float(snapshot.price_usd),
                liquidity_usd=float(snapshot.liquidity_usd or pair.liquidity_usd),
                snapshot_ts=snapshot.ts,
                symbol=token.symbol,
                token_id=token.id,
                pair_id=pair.id,
                token_address=token.address,
                pct_m5=float(snapshot.pct_m5),
                buy_tax_pct=assessment.buy_tax_pct,
                sell_tax_pct=assessment.sell_tax_pct,
                buy_tax_known=assessment.buy_tax_known,
                sell_tax_known=assessment.sell_tax_known,
                recent_prices=recent,
                security_status=assessment.overall,
            ),
            cfg,
        )
        check_quote(quote)

        simulation = simulate_buy(
            chain=token.chain,
            notional_usd=requested,
            price_usd=float(snapshot.price_usd),
            liquidity_usd=float(snapshot.liquidity_usd or pair.liquidity_usd),
            buy_tax_pct=assessment.buy_tax_pct,
            pct_m5=float(snapshot.pct_m5),
            cfg=cfg,
        )

        day = current_trading_day()
        equity_before = await _current_equity(repo, account)
        daily = await repo.ensure_daily(account.id, day, starting_equity=equity_before)
        check_open_slots(await repo.open_position_count(account.id), limits)
        check_daily_loss(daily, limits)
        check_cash(account, simulation.cash_debit)

        order = Order(
            account_id=account.id,
            token_id=token.id,
            side=OrderSide.BUY.value,
            status=OrderStatus.NEW.value,
            client_order_id=client_id,
            requested_notional=_dec(requested),
            qty=_dec(simulation.qty),
            source=request.source,
            meta={"reason": request.reason},
        )
        session.add(order)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise RiskLimitError("Duplicate order id.", code=REASON_DUPLICATE_ORDER) from None

        cost = _dec(simulation.cash_debit)
        account.cash_balance = Decimal(str(account.cash_balance)) - cost
        account.version += 1

        position = Position(
            account_id=account.id,
            token_id=token.id,
            pair_id=pair.id,
            status=PositionStatus.OPEN.value,
            qty=_dec(simulation.qty),
            remaining_qty=_dec(simulation.qty),
            entry_price=_dec(simulation.exec_price),
            entry_notional=_dec(requested),
            entry_fees=_dec(simulation.fees.total_usd),
            entry_cost=cost,
            invested_usd=cost,
            peak_price=_dec(float(snapshot.price_usd)),
            trail_high=_dec(float(snapshot.price_usd)),
            entry_liquidity_usd=_dec(float(snapshot.liquidity_usd)),
            entry_snapshot_ts=snapshot.ts,
            strategy_version=cfg.version if request.source != "manual" else "manual",
            state={"entry_reason": request.reason},
        )
        session.add(position)
        await session.flush()
        order.position_id = position.id

        fill = Fill(
            order_id=order.id,
            position_id=position.id,
            account_id=account.id,
            sector=OrderSide.BUY.value,
            price=_dec(simulation.exec_price),
            qty=_dec(simulation.qty),
            notional=_dec(requested),
            fee_network=_dec(simulation.fees.network_usd),
            fee_dex=_dec(simulation.fees.dex_usd),
            fee_tax=_dec(simulation.fees.tax_usd),
            slippage_pct=simulation.slippage_pct,
            impact_pct=simulation.impact_pct,
            realized_pnl=Decimal("0"),
            price_source_ts=snapshot.ts,
            is_estimate=True,
        )
        session.add(fill)
        order.status = OrderStatus.FILLED.value
        order.fill_price = _dec(simulation.exec_price)
        order.fill_notional = _dec(requested)
        order.filled_at = utc_now()

        daily.entries += 1
        daily.trades += 1
        daily.fees_paid = Decimal(str(daily.fees_paid)) + _dec(simulation.fees.total_usd)
        daily.ending_equity = await _current_equity(repo, account)

        await _queue_notification(
            system,
            kind=NotificationKind.TRADE_ENTRY.value,
            title=f"Paper buy: {token.symbol}",
            message=(
                f"Simulated entry of ${requested:.2f} in {token.name} ({token.symbol}) "
                f"on {token.chain}. Score-based size, all risk checks passed."
            ),
            severity="SUCCESS",
            payload={
                "token_id": token.id,
                "symbol": token.symbol,
                "name": token.name,
                "chain": token.chain,
                "address": token.address,
                "price": float(simulation.exec_price),
                "notional": requested,
                "qty": simulation.qty,
                "entry_fees": simulation.fees.total_usd,
                "impact_pct": simulation.impact_pct,
                "slippage_pct": simulation.slippage_pct,
                "security": assessment.overall,
                "reason": request.reason,
            },
        )

        await session.flush()
        logger.info(
            "paper_buy_filled",
            extra={
                "token_id": token.id,
                "symbol": token.symbol,
                "notional": requested,
                "position_id": position.id,
            },
        )
        outcome = BuyOutcome(
            order=order,
            position=position,
            fill=fill,
            quote=quote,
            assessment=assessment,
            cash_balance=float(account.cash_balance),
        )
    return outcome


async def execute_sell(request: SellRequest, *, account_name: str = "default") -> SellOutcome:
    exit_key = request.exit_key or f"manual-{uuid.uuid4().hex[:24]}"
    async with risk_transaction(account_name=account_name) as (session, account):
        repo = TradingRepository(session)
        tokens = TokenRepository(session)
        system = SystemRepository(session)
        cfg = await load_strategy_config(session)

        existing = await repo.order_by_exit_key(exit_key)
        if existing is not None:
            fills = await repo.fills_for_order(existing.id)
            position = await repo.position(existing.position_id) if existing.position_id else None
            if position is None:
                raise RiskLimitError("Position for this exit is missing.", code=REASON_NO_POSITION)
            return SellOutcome(
                order=existing,
                position=position,
                fill=fills[0] if fills else None,
                duplicate=True,
                realized_pnl=float(fills[0].realized_pnl) if fills else 0.0,
            )

        position = await repo.position(request.position_id, for_update=True)
        if position is None or position.account_id != account.id:
            raise NotFoundError("Open position not found.")
        if position.status != PositionStatus.OPEN.value or Decimal(str(position.remaining_qty)) <= 0:
            raise RiskLimitError("Position is already closed.", code=REASON_NO_POSITION)

        pair = await tokens.primary_pair(position.token_id)
        if pair is None:
            raise RiskLimitError("Pair is no longer available.", code=REASON_STALE_DATA)
        snapshot = await tokens.latest_snapshot(pair.id)
        if snapshot is None or float(snapshot.price_usd) <= 0:
            raise RiskLimitError("No usable market price for the exit.", code=REASON_STALE_DATA)

        remaining = Decimal(str(position.remaining_qty))
        qty_requested = request.qty
        if qty_requested is None:
            ratio = request.ratio if request.ratio is not None else 1.0
            qty_requested = float(remaining) * max(0.0, min(1.0, ratio))
        qty = min(_dec(qty_requested), remaining)
        if qty <= 0:
            raise RiskLimitError("Exit quantity must be positive.", code=REASON_QUANTITY)

        token = await tokens.get(position.token_id)
        if token is None:
            raise NotFoundError("Token not found.")

        checks = await tokens.latest_security([token.id])
        check = checks.get(token.id)
        assessment = assessment_from_check(check) if check is not None else None
        sell_tax = assessment.sell_tax_pct if assessment and assessment.sell_tax_known else 0.0

        simulation = simulate_sell(
            chain=token.chain,
            qty=float(qty),
            price_usd=float(snapshot.price_usd),
            liquidity_usd=float(snapshot.liquidity_usd or pair.liquidity_usd),
            sell_tax_pct=sell_tax,
            pct_m5=float(snapshot.pct_m5),
            cfg=cfg,
        )

        cost_basis = _dec(position.invested_usd) * (qty / remaining)
        proceeds = _dec(simulation.proceeds_usd)
        realized = proceeds - cost_basis

        client_id = f"sell-{uuid.uuid4().hex[:24]}"
        order = Order(
            account_id=account.id,
            token_id=token.id,
            position_id=position.id,
            side=OrderSide.SELL.value,
            status=OrderStatus.FILLED.value,
            client_order_id=client_id,
            exit_key=exit_key,
            requested_notional=_dec(simulation.gross_usd),
            qty=qty,
            fill_price=_dec(simulation.exec_price),
            fill_notional=_dec(simulation.proceeds_usd),
            source=request.source,
            filled_at=utc_now(),
            meta={"reason": request.reason},
        )
        session.add(order)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise RiskLimitError("Duplicate exit.", code=REASON_DUPLICATE_ORDER) from None

        fill = Fill(
            order_id=order.id,
            position_id=position.id,
            account_id=account.id,
            sector=OrderSide.SELL.value,
            price=_dec(simulation.exec_price),
            qty=qty,
            notional=_dec(simulation.gross_usd),
            fee_network=_dec(simulation.fees.network_usd),
            fee_dex=_dec(simulation.fees.dex_usd),
            fee_tax=_dec(simulation.fees.tax_usd),
            slippage_pct=simulation.slippage_pct,
            impact_pct=simulation.impact_pct,
            realized_pnl=realized,
            price_source_ts=snapshot.ts,
            is_estimate=True,
        )
        session.add(fill)

        position.remaining_qty = remaining - qty
        position.invested_usd = _dec(position.invested_usd) - cost_basis
        position.realized_pnl = _dec(position.realized_pnl) + realized
        position.fees_paid = _dec(position.fees_paid) + _dec(simulation.fees.total_usd)
        position.peak_price = max(_dec(position.peak_price), _dec(snapshot.price_usd))
        position.trail_high = max(_dec(position.trail_high), _dec(snapshot.price_usd))
        closed = position.remaining_qty <= Decimal("0.0000000001")
        if closed:
            position.remaining_qty = Decimal("0")
            position.status = PositionStatus.CLOSED.value
            position.closed_at = utc_now()
            position.exit_reason = request.reason

        account.cash_balance = Decimal(str(account.cash_balance)) + proceeds
        account.realized_pnl = _dec(account.realized_pnl) + realized
        account.version += 1

        day = current_trading_day()
        equity_before = await _current_equity(repo, account) - proceeds
        daily = await repo.ensure_daily(account.id, day, starting_equity=equity_before)
        daily.realized_pnl = _dec(daily.realized_pnl) + realized
        daily.fees_paid = _dec(daily.fees_paid) + _dec(simulation.fees.total_usd)
        daily.exits += 1
        daily.trades += 1
        just_halted = False
        if loss_limit_reached(daily, cfg.daily_loss_limit_usd) and not daily.halted:
            daily.halted = True
            account.is_halted = True
            just_halted = True
        daily.ending_equity = await _current_equity(repo, account)

        kind = NotificationKind.FULL_EXIT.value if closed else NotificationKind.PARTIAL_PROFIT.value
        if request.reason == "STOP_LOSS":
            kind = NotificationKind.STOP_LOSS.value
            severity = "CRITICAL"
        else:
            severity = "SUCCESS" if realized >= 0 else "WARNING"

        await _queue_notification(
            system,
            kind=kind,
            title=f"Paper exit: {token.symbol} ({request.reason.replace('_', ' ').title()})",
            message=(
                f"Sold {'100' if closed else 'part'} of the simulated {token.symbol} position "
                f"for ${float(proceeds):.2f}. Net P&L {float(realized):+.2f} USD."
            ),
            severity=severity,
            payload={
                "token_id": token.id,
                "symbol": token.symbol,
                "chain": token.chain,
                "address": token.address,
                "reason": request.reason,
                "qty": float(qty),
                "price": float(simulation.exec_price),
                "proceeds": float(proceeds),
                "realized_pnl": float(realized),
                "closed": closed,
                "security": assessment.overall if assessment else "UNKNOWN",
            },
        )

        if just_halted:
            await _queue_notification(
                system,
                kind=NotificationKind.DAILY_LOSS_LIMIT.value,
                title="Daily paper loss limit reached",
                message=(
                    f"Realised loss reached the ${cfg.daily_loss_limit_usd:.2f} daily cap. "
                    "No new paper entries will be opened until the next trading day."
                ),
                severity="CRITICAL",
                payload={"realized": float(daily.realized_pnl), "limit": cfg.daily_loss_limit_usd},
            )

        await session.flush()
        logger.info(
            "paper_sell_filled",
            extra={
                "position_id": position.id,
                "symbol": token.symbol,
                "qty": float(qty),
                "realized": float(realized),
                "closed": closed,
            },
        )
        outcome = SellOutcome(
            order=order,
            position=position,
            fill=fill,
            realized_pnl=float(realized),
            proceeds_usd=float(proceeds),
        )
    return outcome


async def _queue_notification(
    system: SystemRepository,
    *,
    kind: str,
    title: str,
    message: str,
    severity: str,
    payload: dict,
) -> None:
    if not settings.discord_enabled:
        return
    await system.add_notification(
        kind=kind, title=title, message=message, severity=severity, payload=payload
    )


async def update_position_state(
    position_id: int,
    *,
    arm_protection: bool = False,
    stop_price: float | None = None,
    trail_high: float | None = None,
) -> None:
    """Persist protection arming and trailing-peak updates without creating an order."""
    async with risk_transaction() as (session, _account):
        position = await session.get(Position, position_id, with_for_update=True)
        if position is None:
            return
        if arm_protection:
            position.protection_armed = True
        if stop_price is not None:
            position.stop_price = _dec(stop_price)
        if trail_high is not None:
            position.trail_high = max(_dec(position.trail_high), _dec(trail_high))
            position.peak_price = max(_dec(position.peak_price), _dec(trail_high))
        await session.flush()

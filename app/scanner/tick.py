"""One scanner tick: discover → enrich → analyse → trade → persist → notify.

Every stage is individually guarded so a single provider outage degrades the
tick instead of failing it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.clock import utc_now
from app.core.config import settings
from app.core.errors import RiskLimitError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.execution.simulator import estimate_roundtrip_cost_pct
from app.models import (
    MarketSnapshot,
    OpportunityScore,
    Pair,
    Position,
    ScannerRun,
    SecurityCheck,
    Token,
)
from app.models.enums import DecisionAction, NotificationKind, ScannerRunStatus, SecurityStatus
from app.notifications.dispatcher import NotificationDispatcher
from app.providers.registry import Providers
from app.repositories.system import SystemRepository
from app.repositories.tokens import TokenRepository
from app.repositories.trading import TradingRepository
from app.risk.limits import RiskLimits
from app.scanner.discovery import discover_new_pools
from app.scanner.enrichment import enrich_quotes
from app.scanner.retention import downsample_and_prune
from app.scanner.rotation import select_candidates
from app.services.events import EventHub
from app.services.scoring import ScoreInputs, compute_score
from app.services.security import (
    CRITICAL_FIELDS,
    SecurityAssessment,
    assessment_from_check,
    check_token,
)
from app.services.settings_service import (
    load_notification_config,
    load_scanner_config,
    load_strategy_config,
)
from app.services.trade_service import (
    BuyRequest,
    SellRequest,
    execute_buy,
    execute_sell,
    update_position_state,
)
from app.strategies.config import StrategyConfig
from app.strategies.exits import evaluate_exit
from app.strategies.strategy_a import evaluate_entry
from app.strategies.types import EntryContext, PositionView, SnapshotPoint

logger = get_logger(__name__)


@dataclass(slots=True)
class TickResult:
    status: str = ScannerRunStatus.SKIPPED.value
    skipped_reason: str | None = None
    run_id: int | None = None
    discovered: int = 0
    enriched: int = 0
    snapshots: int = 0
    scored: int = 0
    entries: int = 0
    exits: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: int = 0
    error_summary: str | None = None
    timings: dict[str, int] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "skipped_reason": self.skipped_reason,
            "run_id": self.run_id,
            "discovered": self.discovered,
            "enriched": self.enriched,
            "snapshots": self.snapshots,
            "scored": self.scored,
            "entries": self.entries,
            "exits": self.exits,
            "skipped": self.skipped,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "error_summary": self.error_summary,
            "timings": self.timings,
            "trades": self.trades,
        }


@dataclass(slots=True)
class Candidate:
    token: Token
    pair: Pair
    snapshot: MarketSnapshot
    series: list[SnapshotPoint]
    check: SecurityCheck | None
    previous_score: OpportunityScore | None
    position: Position | None = None


@dataclass(slots=True)
class Plan:
    candidate: Candidate
    assessment: SecurityAssessment
    scored: Any
    decision: str
    reason_codes: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    signal_strength: float = 0.0
    exit_action: Any = None
    entry_signal: Any = None


def _to_points(rows: list[MarketSnapshot]) -> list[SnapshotPoint]:
    return [
        SnapshotPoint(
            ts=row.ts,
            price=float(row.price_usd),
            liquidity=float(row.liquidity_usd),
            volume_m5=float(row.volume_m5),
            volume_h1=float(row.volume_h1),
            buys_h1=row.buys_h1,
            sells_h1=row.sells_h1,
            buys_m5=row.buys_m5,
            sells_m5=row.sells_m5,
            pct_m5=float(row.pct_m5),
            pct_h1=float(row.pct_h1),
        )
        for row in rows
    ]


class ScannerEngine:
    def __init__(
        self,
        providers: Providers,
        hub: EventHub,
        dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self.providers = providers
        self.hub = hub
        self.dispatcher = dispatcher
        self._last_retention: datetime | None = None

    async def tick(self, source: str = "loop") -> TickResult:
        started = time.perf_counter()
        result = TickResult()
        lap_at = started

        def lap(name: str) -> None:
            nonlocal lap_at
            now = time.perf_counter()
            result.timings[name] = int((now - lap_at) * 1000)
            lap_at = now

        cfg = StrategyConfig()
        scan_cfg: dict[str, Any] = {}
        notif_cfg: dict[str, Any] = {}
        try:
            async with session_scope() as session:
                cfg = await load_strategy_config(session)
                scan_cfg = await load_scanner_config(session)
                notif_cfg = await load_notification_config(session)
                run = await SystemRepository(session).start_run(source)
                result.run_id = run.id

            if not scan_cfg.get("enabled", True):
                result.status = ScannerRunStatus.SKIPPED.value
                result.skipped_reason = "Scanner is disabled in settings."
                return await self._finish(result, cfg, started)

            limits = RiskLimits.from_config(cfg)
            now = utc_now()
            window_start = now - timedelta(hours=float(scan_cfg.get("discovery_window_hours", 6.0)))

            pools, discovery_errors = await discover_new_pools(
                self.providers,
                window_start=window_start,
                pages=settings.gt_discovery_pages,
            )
            result.errors += len(discovery_errors)
            lap("discovery_ms")

            new_token_ids: list[int] = []
            async with session_scope() as session:
                tokens_repo = TokenRepository(session)
                known_tokens = await tokens_repo.tokens_by_addresses(
                    (pool.chain, pool.token_address) for pool in pools
                )
                known_pairs = await tokens_repo.pairs_by_addresses(
                    (pool.chain, pool.pool_address) for pool in pools
                )
                for pool in pools:
                    existing = known_tokens.get((pool.chain, pool.token_address))
                    token, _pair = await tokens_repo.upsert_discovery(
                        pool,
                        seen_at=now,
                        token=existing,
                        pair=known_pairs.get((pool.chain, pool.pool_address)),
                    )
                    if existing is None:
                        new_token_ids.append(token.id)
                        result.discovered += 1
            lap("ingest_ms")

            async with session_scope() as session:
                selected, _positions = await select_candidates(
                    session,
                    window_start=window_start,
                    limit=max(settings.scanner_candidates_per_tick, 5),
                )
                selected_ids = [token.id for token in selected]

            quotes_by_address, enrich_errors = await enrich_quotes(
                self.providers,
                [token.address for token in selected],
                batch_size=settings.ds_batch_size,
                max_batches=settings.max_ds_batches_per_tick,
            )
            result.errors += len(enrich_errors)
            result.enriched = sum(len(items) for items in quotes_by_address.values())
            lap("enrich_ms")

            candidates = await self._materialise(
                selected_ids, quotes_by_address, run_id=result.run_id, now=now
            )
            result.snapshots = len(candidates)
            lap("snapshot_ms")

            async with session_scope() as session:
                account = await TradingRepository(session).account()
                available_cash = float(account.cash_balance) if account else 0.0

            assessments = await self._assess(candidates, cfg)
            lap("security_ms")
            plans = self._plan(candidates, assessments, cfg, limits, available_cash)

            trades = await self._execute(plans, limits)
            result.trades = trades
            result.entries = sum(
                1
                for t in trades
                if t["side"] == "BUY" and not t.get("duplicate") and not t.get("skipped")
            )
            result.exits = sum(
                1
                for t in trades
                if t["side"] == "SELL" and not t.get("duplicate") and not t.get("skipped")
            )
            result.skipped = sum(1 for t in trades if t.get("skipped"))
            lap("trade_ms")

            await self._persist(plans, result, cfg, notif_cfg, limits)
            lap("persist_ms")

            if discovery_errors or enrich_errors:
                result.status = ScannerRunStatus.DEGRADED.value
                result.error_summary = "; ".join((discovery_errors + enrich_errors)[:3])
            else:
                result.status = ScannerRunStatus.COMPLETED.value
        except Exception as exc:  # noqa: BLE001 - the tick must record and survive
            logger.exception("scanner_tick_failed")
            result.status = ScannerRunStatus.FAILED.value
            result.errors += 1
            result.error_summary = f"{type(exc).__name__}: {exc}"

        return await self._finish(result, cfg, started)

    # ------------------------------------------------------------------
    async def _materialise(
        self,
        token_ids: list[int],
        quotes_by_address: dict[str, list],
        *,
        run_id: int | None,
        now: datetime,
    ) -> list[Candidate]:
        cutoff = now - timedelta(hours=settings.discovery_window_hours)
        async with session_scope() as session:
            tokens = TokenRepository(session)
            trading = TradingRepository(session)
            selected = await tokens.get_many(token_ids)
            by_id = {t.id: t for t in selected}

            for token in selected:
                quotes = quotes_by_address.get(token.address.lower()) or []
                if quotes:
                    best = max(quotes, key=lambda q: float(q.liquidity_usd or 0))
                    await tokens.apply_quote(token, best, seen_at=now)

            ids = list(by_id)
            pairs = await tokens.primary_pairs(ids)
            latest = await tokens.latest_snapshots(ids)
            for token in selected:
                pair = pairs.get(token.id)
                if pair is None:
                    continue
                snapshot = latest.get(token.id)
                if snapshot is None or (now - snapshot.ts).total_seconds() >= 25:
                    latest[token.id] = await tokens.add_snapshot(
                        token, pair, ts=now, run_id=run_id
                    )

            positions = await trading.all_open_positions()
            positions_by_token = {p.token_id: p for p in positions}
            checks = await tokens.latest_security(ids)
            scores = await tokens.latest_scores(ids)

            candidates: list[Candidate] = []
            for token in selected:
                pair = pairs.get(token.id)
                snapshot = latest.get(token.id)
                if pair is None or snapshot is None:
                    continue
                rows = await tokens.snapshots_for_pair(pair.id, since=cutoff, limit=240)
                candidates.append(
                    Candidate(
                        token=token,
                        pair=pair,
                        snapshot=snapshot,
                        series=_to_points(rows),
                        check=checks.get(token.id),
                        previous_score=scores.get(token.id),
                        position=positions_by_token.get(token.id),
                    )
                )
            return candidates

    async def _assess(
        self, candidates: list[Candidate], cfg: StrategyConfig
    ) -> dict[int, SecurityAssessment]:
        now = utc_now()
        assessments: dict[int, SecurityAssessment] = {}
        refresh: list[Candidate] = []
        for candidate in candidates:
            check = candidate.check
            age = (now - check.ts).total_seconds() if check else 10_000
            needs = check is None or age > 900 or candidate.token.chain == "solana" and age > 600
            if needs:
                refresh.append(candidate)
            elif check is not None:
                assessments[candidate.token.id] = assessment_from_check(check)

        # Positions first, then the rest; keep provider usage inside the budget.
        refresh.sort(key=lambda c: (c.position is None, c.token.symbol))
        budget = max(1, settings.scanner_security_refresh_per_tick)
        for candidate in refresh[:budget]:
            try:
                assessment, _gp, _rc = await check_token(
                    self.providers, candidate.token.chain, candidate.token.address
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("security_check_failed", extra={"error": str(exc)})
                if candidate.check is not None:
                    assessments[candidate.token.id] = assessment_from_check(candidate.check)
                continue
            assessments[candidate.token.id] = assessment
            async with session_scope() as session:
                token = await session.get(Token, candidate.token.id)
                if token is not None:
                    await TokenRepository(session).store_security(token, assessment, ts=now)

        for candidate in candidates:
            assessments.setdefault(
                candidate.token.id,
                assessment_from_check(candidate.check)
                if candidate.check is not None
                else _unavailable(candidate.token),
            )
        return assessments

    def _plan(
        self,
        candidates: list[Candidate],
        assessments: dict[int, SecurityAssessment],
        cfg: StrategyConfig,
        limits: RiskLimits,
        available_cash: float,
    ) -> list[Plan]:
        plans: list[Plan] = []
        for candidate in candidates:
            assessment = assessments[candidate.token.id]
            scored = self._score(candidate, assessment)
            metrics: dict[str, Any] = {
                "score": scored.score,
                "confidence": scored.confidence,
                "security": assessment.overall,
                "price": float(candidate.snapshot.price_usd),
                "liquidity": float(candidate.snapshot.liquidity_usd),
                "age_seconds": round((utc_now() - candidate.snapshot.ts).total_seconds(), 1),
            }

            if candidate.position is not None:
                view = PositionView(
                    position_id=candidate.position.id,
                    entry_price=float(candidate.position.entry_price),
                    qty=float(candidate.position.qty),
                    remaining_qty=float(candidate.position.remaining_qty),
                    peak_price=float(candidate.position.peak_price),
                    trail_high=float(candidate.position.trail_high),
                    protection_armed=candidate.position.protection_armed,
                    entry_liquidity_usd=float(candidate.position.entry_liquidity_usd),
                    invested_usd=float(candidate.position.invested_usd),
                    entry_fees=float(candidate.position.entry_fees),
                )
                action = evaluate_exit(
                    view,
                    candidate.series,
                    cfg,
                    security_status=assessment.overall,
                    security_critical_unknown=assessment.critical_unknown > 0,
                )
                decision = DecisionAction.EXIT.value if action and action.action == "SELL" else DecisionAction.HOLD.value
                reason_codes = [action.reason] if action else []
                if action:
                    metrics.update(action.metrics)
                plans.append(
                    Plan(
                        candidate=candidate,
                        assessment=assessment,
                        scored=scored,
                        decision=decision,
                        reason_codes=reason_codes,
                        metrics=metrics,
                        exit_action=action,
                    )
                )
                continue

            held = any(p.candidate.position is not None for p in plans)
            roundtrip = estimate_roundtrip_cost_pct(
                chain=candidate.token.chain,
                notional_usd=limits.max_position_usd,
                liquidity_usd=float(candidate.snapshot.liquidity_usd),
                buy_tax_pct=assessment.buy_tax_pct,
                sell_tax_pct=assessment.sell_tax_pct,
                pct_m5=float(candidate.snapshot.pct_m5),
            )
            context = EntryContext(
                score=scored.score,
                confidence=scored.confidence,
                security_status=assessment.overall,
                security_eligible=assessment.eligible,
                critical_unknown=assessment.critical_unknown,
                warning_count=assessment.warning_count,
                roundtrip_cost_pct=roundtrip,
                available_cash=max(0.0, available_cash - 0.001),
                max_position_usd=limits.max_position_usd,
                now=utc_now(),
            )
            signal = evaluate_entry(candidate.series, context, cfg)
            decision = DecisionAction.ENTER.value if signal.accepted else DecisionAction.REJECT.value
            metrics.update(signal.metrics)
            metrics["roundtrip_cost_pct"] = roundtrip
            metrics["held_elsewhere"] = held
            plans.append(
                Plan(
                    candidate=candidate,
                    assessment=assessment,
                    scored=scored,
                    decision=decision,
                    reason_codes=signal.reason_codes,
                    metrics=metrics,
                    signal_strength=signal.strength,
                    entry_signal=signal,
                )
            )
        return plans

    def _score(self, candidate: Candidate, assessment: SecurityAssessment):
        snapshot = candidate.snapshot
        prices = [point.price for point in candidate.series[-40:]]
        providers_total = 2 if candidate.token.chain == "solana" else 1
        providers_available = sum(1 for value in assessment.providers.values() if value)
        if providers_available == 0 and assessment.overall != SecurityStatus.UNAVAILABLE.value:
            providers_available = 1
        inputs = ScoreInputs(
            liquidity_usd=float(snapshot.liquidity_usd),
            volume_h1=float(snapshot.volume_h1),
            volume_m5=float(snapshot.volume_m5),
            buys_h1=snapshot.buys_h1,
            sells_h1=snapshot.sells_h1,
            pct_h1=float(snapshot.pct_h1),
            pct_m5=float(snapshot.pct_m5),
            holder_concentration=assessment.holder_concentration,
            holder_count=assessment.holder_count,
            security_overall=assessment.overall,
            critical_pass=assessment.critical_pass,
            critical_total=assessment.critical_total,
            providers_available=providers_available,
            providers_total=providers_total,
            snapshot_age_seconds=(utc_now() - snapshot.ts).total_seconds(),
            history_points=len(candidate.series),
            prices=prices,
        )
        return compute_score(inputs, assessment.risk_score)

    async def _execute(self, plans: list[Plan], limits: RiskLimits) -> list[dict[str, Any]]:
        trades: list[dict[str, Any]] = []
        for plan in plans:
            action = plan.exit_action
            position = plan.candidate.position
            if position is None or action is None:
                continue
            token = plan.candidate.token
            if action.action == "UPDATE_STATE":
                try:
                    await update_position_state(
                        position.id,
                        arm_protection=action.arm_protection,
                        stop_price=action.new_stop_price,
                        trail_high=plan.metrics.get("price"),
                    )
                    trades.append(
                        {
                            "side": "UPDATE",
                            "token_id": token.id,
                            "symbol": token.symbol,
                            "reason": action.reason,
                            "duplicate": False,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("position_state_update_failed", extra={"error": str(exc)})
                continue

            try:
                outcome = await execute_sell(
                    SellRequest(
                        position_id=position.id,
                        ratio=action.ratio or 1.0,
                        reason=action.reason,
                        exit_key=f"pos{position.id}:{action.exit_key}",
                        source="scanner",
                    )
                )
                trades.append(
                    {
                        "side": "SELL",
                        "token_id": token.id,
                        "symbol": token.symbol,
                        "position_id": position.id,
                        "order_id": outcome.order.id,
                        "reason": action.reason,
                        "realized_pnl": outcome.realized_pnl,
                        "duplicate": outcome.duplicate,
                    }
                )
                await self.hub.publish(
                    "trade.exit",
                    {
                        "token_id": token.id,
                        "symbol": token.symbol,
                        "reason": action.reason,
                        "realized_pnl": outcome.realized_pnl,
                    },
                )
            except RiskLimitError as exc:
                plan.reason_codes.append(exc.code)
                trades.append(
                    {
                        "side": "SELL",
                        "token_id": token.id,
                        "symbol": token.symbol,
                        "skipped": True,
                        "error": exc.message,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("exit_failed")
                trades.append(
                    {
                        "side": "SELL",
                        "token_id": token.id,
                        "symbol": token.symbol,
                        "skipped": True,
                        "error": str(exc),
                    }
                )

        entry_plans = [p for p in plans if p.candidate.position is None and p.decision == DecisionAction.ENTER.value]
        entry_plans.sort(key=lambda p: p.scored.score, reverse=True)
        async with session_scope() as session:
            repo = TradingRepository(session)
            account = await repo.account()
            open_count = await repo.open_position_count(account.id) if account else 0
        remaining_slots = max(0, limits.max_open_positions - open_count)

        for plan in entry_plans:
            token = plan.candidate.token
            signal = plan.entry_signal
            if remaining_slots <= 0:
                plan.decision = DecisionAction.REJECT.value
                plan.reason_codes.append("MAX_POSITIONS")
                continue
            try:
                outcome = await execute_buy(
                    BuyRequest(
                        token_id=token.id,
                        notional_usd=signal.size_usd if signal else None,
                        client_order_id=f"scan:{token.id}:{int(plan.candidate.snapshot.ts.timestamp())}",
                        source="scanner",
                        reason="Conservative momentum pullback entry",
                    )
                )
                if outcome.duplicate:
                    plan.decision = DecisionAction.HOLD.value
                    plan.reason_codes.append("DUPLICATE_ORDER")
                trades.append(
                    {
                        "side": "BUY",
                        "token_id": token.id,
                        "symbol": token.symbol,
                        "order_id": outcome.order.id,
                        "notional": float(outcome.order.requested_notional),
                        "duplicate": outcome.duplicate,
                    }
                )
                if not outcome.duplicate:
                    remaining_slots -= 1
                    await self.hub.publish(
                        "trade.entry",
                        {
                            "token_id": token.id,
                            "symbol": token.symbol,
                            "notional": float(outcome.order.requested_notional),
                            "price": float(outcome.order.fill_price or 0),
                        },
                    )
            except RiskLimitError as exc:
                plan.decision = DecisionAction.REJECT.value
                plan.reason_codes.append(exc.code)
                trades.append(
                    {
                        "side": "BUY",
                        "token_id": token.id,
                        "symbol": token.symbol,
                        "skipped": True,
                        "error": exc.message,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("entry_failed")
                trades.append(
                    {
                        "side": "BUY",
                        "token_id": token.id,
                        "symbol": token.symbol,
                        "skipped": True,
                        "error": str(exc),
                    }
                )
        return trades

    async def _persist(
        self,
        plans: list[Plan],
        result: TickResult,
        cfg: StrategyConfig,
        notif_cfg: dict[str, Any],
        limits: RiskLimits,
    ) -> None:
        now = utc_now()
        async with session_scope() as session:
            tokens = TokenRepository(session)
            system = SystemRepository(session)
            stored_scores = 0
            decisions_stored = 0
            for plan in plans:
                token = plan.candidate.token
                row = await tokens.add_score(
                    token,
                    plan.candidate.pair,
                    score=plan.scored.score,
                    confidence=plan.scored.confidence,
                    security_risk=plan.scored.security_risk,
                    signal_strength=plan.signal_strength,
                    rank_score=plan.scored.rank_score,
                    components=plan.scored.components,
                    explanations=plan.scored.explanations,
                    decision=plan.decision,
                    rejection_codes=plan.reason_codes,
                    ts=now,
                )
                stored_scores += 1
                should_store_decision = plan.decision in {
                    DecisionAction.ENTER.value,
                    DecisionAction.EXIT.value,
                }
                if should_store_decision or decisions_stored < 8:
                    await system.add_decision(
                        token_id=token.id,
                        pair_id=plan.candidate.pair.id,
                        position_id=plan.candidate.position.id if plan.candidate.position else None,
                        action=plan.decision,
                        reason_codes=plan.reason_codes,
                        metrics=plan.metrics,
                    )
                    decisions_stored += 1
                _ = row

                previous_check_status = plan.candidate.check.overall if plan.candidate.check else None
                if (
                    notif_cfg.get("enabled", True)
                    and plan.assessment.overall == SecurityStatus.FAIL.value
                    and previous_check_status != SecurityStatus.FAIL.value
                ):
                    await system.add_notification(
                        kind=NotificationKind.SECURITY_FAILURE.value,
                        title=f"Security failure: {token.symbol}",
                        message=plan.assessment.summary(),
                        severity="CRITICAL",
                        payload={
                            "token_id": token.id,
                            "symbol": token.symbol,
                            "name": token.name,
                            "chain": token.chain,
                            "address": token.address,
                            "price": plan.metrics.get("price"),
                            "security": plan.assessment.overall,
                            "reason": "; ".join(plan.assessment.reasons[:3]),
                        },
                    )
                elif (
                    notif_cfg.get("enabled", True)
                    and notif_cfg.get("notify_security_warnings", False)
                    and plan.assessment.overall == SecurityStatus.WARNING.value
                    and previous_check_status not in {
                        SecurityStatus.WARNING.value,
                        SecurityStatus.FAIL.value,
                    }
                ):
                    await system.add_notification(
                        kind=NotificationKind.SECURITY_WARNING.value,
                        title=f"Security warning: {token.symbol}",
                        message=plan.assessment.summary(),
                        severity="WARNING",
                        payload={
                            "token_id": token.id,
                            "symbol": token.symbol,
                            "chain": token.chain,
                            "address": token.address,
                            "price": plan.metrics.get("price"),
                            "security": plan.assessment.overall,
                            "reason": "; ".join(plan.assessment.reasons[:3]),
                        },
                    )

                previous = plan.candidate.previous_score
                threshold = float(notif_cfg.get("min_score_for_alert", 70.0))
                if (
                    notif_cfg.get("enabled", True)
                    and plan.candidate.position is None
                    and plan.decision != DecisionAction.ENTER.value
                    and plan.scored.score >= threshold
                    and (previous is None or previous.score < threshold)
                ):
                    await system.add_notification(
                        kind=NotificationKind.HIGH_SCORE_TOKEN.value,
                        title=f"High-score opportunity: {token.symbol}",
                        message=(
                            f"{token.name} ({token.symbol}) on {token.chain} scored "
                            f"{plan.scored.score:.1f}/100 with confidence {plan.scored.confidence:.0%}. "
                            f"Security {plan.assessment.overall}."
                        ),
                        severity="INFO",
                        payload={
                            "token_id": token.id,
                            "symbol": token.symbol,
                            "name": token.name,
                            "chain": token.chain,
                            "address": token.address,
                            "price": plan.metrics.get("price"),
                            "score": plan.scored.score,
                            "security": plan.assessment.overall,
                        },
                    )
            result.scored = stored_scores

            # Keep trailing highs current for every open position.
            for position in await TradingRepository(session).all_open_positions():
                snapshot = (
                    await tokens.latest_snapshot(position.pair_id) if position.pair_id else None
                )
                if snapshot is None:
                    continue
                price = float(snapshot.price_usd)
                if price > float(position.trail_high):
                    position.trail_high = price
                if price > float(position.peak_price):
                    position.peak_price = price

            if self._last_retention is None or (now - self._last_retention) > timedelta(minutes=30):
                try:
                    await downsample_and_prune(session)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("retention_failed", extra={"error": str(exc)})
                self._last_retention = now

        await self.hub.publish(
            "scan.complete",
            {
                "run_id": result.run_id,
                "status": result.status,
                "discovered": result.discovered,
                "entries": result.entries,
                "exits": result.exits,
                "errors": result.errors,
            },
        )
        if self.dispatcher is not None:
            try:
                await self.dispatcher.dispatch_pending()
            except Exception as exc:  # noqa: BLE001
                logger.warning("notification_dispatch_failed", extra={"error": str(exc)})

    async def _finish(self, result: TickResult, cfg: StrategyConfig, started: float) -> TickResult:
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        if result.run_id is None:
            return result
        try:
            async with session_scope() as session:
                run = await session.get(ScannerRun, result.run_id)
                if run is not None:
                    await SystemRepository(session).finish_run(
                        run,
                        status=result.status,
                        discovered=result.discovered,
                        enriched=result.enriched,
                        snapshots=result.snapshots,
                        scored=result.scored,
                        entries=result.entries,
                        exits=result.exits,
                        skipped=result.skipped,
                        errors=result.errors,
                        error_summary=result.error_summary,
                    )
        except Exception:  # noqa: BLE001
            logger.exception("scanner_run_finalise_failed")
        return result


def _unavailable(token: Token) -> SecurityAssessment:
    return SecurityAssessment(
        chain=token.chain,
        token_address=token.address,
        overall=SecurityStatus.UNAVAILABLE.value,
        eligible=False,
        critical_pass=0,
        critical_total=len(CRITICAL_FIELDS.get(token.chain, ())),
        warning_count=0,
        critical_unknown=len(CRITICAL_FIELDS.get(token.chain, ())),
        risk_score=95.0,
        fields={},
        reasons=["No security data could be collected for this token."],
        providers={},
        buy_tax_known=False,
        sell_tax_known=False,
    )

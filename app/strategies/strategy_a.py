"""Strategy A - Conservative Momentum Pullback.

Pure function over a snapshot series: no database, no network. The scanner
feeds it market snapshots and the result is logged whether accepted or not so
the strategy can be evaluated later.
"""

from __future__ import annotations

from app.strategies.config import StrategyConfig
from app.strategies.indicators import (
    band_pct,
    clamp,
    log_slope,
    pct_change,
    safe_div,
    sma,
)
from app.strategies.types import EntryContext, EntrySignal, SnapshotPoint

RECOVERY_MIN_PCT = 0.5


def _reject(
    codes: list[str], reasons: list[str], metrics: dict[str, float | int | str], strength: float
) -> EntrySignal:
    return EntrySignal(
        action="REJECT",
        strength=round(strength, 4),
        reason_codes=codes,
        reasons=reasons,
        metrics=metrics,
    )


def _liquidity_baseline(series: list[SnapshotPoint], minutes: float = 30.0) -> float:
    last_ts = series[-1].ts
    for point in reversed(series):
        if (last_ts - point.ts).total_seconds() >= minutes * 60:
            return point.liquidity
    return series[0].liquidity


def evaluate_entry(
    series: list[SnapshotPoint], ctx: EntryContext, cfg: StrategyConfig
) -> EntrySignal:
    ordered = sorted(series, key=lambda point: point.ts)
    # Only the newest continuous run of snapshots counts. A scanner restart
    # leaves a gap in history; judging the token on data from before that gap
    # would silently treat the downtime as missing observation.
    start_index = 0
    for index in range(len(ordered) - 1, 0, -1):
        gap = (ordered[index].ts - ordered[index - 1].ts).total_seconds()
        if gap > cfg.max_snapshot_gap_seconds:
            start_index = index
            break
    ordered = ordered[start_index:]
    metrics: dict[str, float | int | str] = {"snapshots": len(ordered)}
    if len(ordered) < 2:
        return _reject(
            ["INSUFFICIENT_OBSERVATION"],
            ["Not enough market snapshots to evaluate the token yet."],
            metrics,
            0.0,
        )

    span_minutes = (ordered[-1].ts - ordered[0].ts).total_seconds() / 60.0
    gaps = [
        (later.ts - earlier.ts).total_seconds()
        for earlier, later in zip(ordered, ordered[1:], strict=False)
    ]
    max_gap = max(gaps) if gaps else 0.0
    metrics.update(
        {
            "observation_minutes": round(span_minutes, 2),
            "max_gap_seconds": round(max_gap, 1),
            "missing_gap": False,
        }
    )
    if (
        len(ordered) < cfg.min_snapshots
        or span_minutes < cfg.min_observation_minutes
        or max_gap > cfg.max_snapshot_gap_seconds
    ):
        metrics["missing_gap"] = True
        return _reject(
            ["INSUFFICIENT_OBSERVATION"],
            [
                f"Observation requirement not met: {len(ordered)} snapshots over "
                f"{span_minutes:.1f} min (need {cfg.min_snapshots} over "
                f"{cfg.min_observation_minutes:.0f} min, max gap {cfg.max_snapshot_gap_seconds}s)."
            ],
            metrics,
            0.0,
        )

    prices = [point.price for point in ordered]
    last = ordered[-1]
    first = ordered[0]
    peak = max(prices)
    drawdown = (peak - last.price) / peak * 100.0 if peak > 0 else 0.0
    h1_pct = last.pct_h1 if last.pct_h1 else pct_change(last.price, first.price)
    slope = log_slope(prices[- min(30, len(prices)) :])
    sma_value = sma(prices, cfg.sma_window)
    price_vs_sma = pct_change(last.price, sma_value)
    last_changes = [pct_change(b, a) for a, b in zip(prices[-3:-1], prices[-2:], strict=False)]
    liquidity_baseline = _liquidity_baseline(ordered)
    turnover = safe_div(last.volume_h1, last.liquidity)
    ratio = safe_div(last.buys_h1, max(1, last.sells_h1))
    recent_prices = prices[-3:]
    recent_band = band_pct(recent_prices) if len(recent_prices) >= 3 else 0.0
    recovery = last.price >= min(recent_prices) * (1 + RECOVERY_MIN_PCT / 100)

    metrics.update(
        {
            "pct_h1": round(h1_pct, 2),
            "pct_m5": round(last.pct_m5, 2),
            "drawdown_pct": round(drawdown, 2),
            "trend_slope": round(slope, 6),
            "price_vs_sma_pct": round(price_vs_sma, 2),
            "liquidity_usd": round(last.liquidity, 2),
            "liquidity_baseline_usd": round(liquidity_baseline, 2),
            "turnover_h1": round(turnover, 4),
            "buy_sell_ratio": round(ratio, 3),
            "stabilization_band_pct": round(recent_band, 2),
            "score": ctx.score,
            "confidence": ctx.confidence,
            "security_status": ctx.security_status,
            "roundtrip_cost_pct": ctx.roundtrip_cost_pct,
        }
    )

    codes: list[str] = []
    reasons: list[str] = []

    if ctx.cooldown_active:
        codes.append("COOLDOWN")
        reasons.append("Recently exited this token; cooling down before re-entry.")

    if h1_pct > cfg.trend_max_pct_h1:
        codes.append("VERTICAL_CANDLE")
        reasons.append(f"One-hour move of {h1_pct:.1f}% is an unsustainable vertical candle.")
    elif h1_pct < cfg.trend_min_pct_h1 or slope <= 0:
        codes.append("NO_TREND")
        reasons.append(
            f"No meaningful upward trend (1h change {h1_pct:.1f}%, slope {slope:.5f})."
        )

    if last.pct_m5 > cfg.max_pct_m5:
        codes.append("VERTICAL_CANDLE")
        reasons.append(f"Price is up {last.pct_m5:.1f}% in five minutes - refusing to chase.")
    if sma_value > 0 and price_vs_sma > cfg.max_price_vs_sma_pct:
        codes.append("VERTICAL_CANDLE")
        reasons.append(f"Price is {price_vs_sma:.1f}% above its {cfg.sma_window}-snapshot average.")
    if len(last_changes) >= 2 and all(change > 8.0 for change in last_changes):
        codes.append("VERTICAL_CANDLE")
        reasons.append("Two consecutive candles above 8% indicate a spike, not a pullback.")

    if drawdown < cfg.pullback_min_pct:
        codes.append("NO_PULLBACK")
        reasons.append(f"Price is only {drawdown:.1f}% below its peak; waiting for a pullback.")
    elif drawdown > cfg.pullback_max_pct:
        codes.append("PULLBACK_TOO_DEEP")
        reasons.append(f"Pullback of {drawdown:.1f}% is too deep for a conservative entry.")

    if recent_band > cfg.stabilization_band_pct or not recovery:
        codes.append("NO_STABILIZATION")
        reasons.append(
            f"Price has not stabilised yet (3-snapshot band {recent_band:.1f}%)."
        )

    if last.liquidity < cfg.min_liquidity_usd:
        codes.append("THIN_LIQUIDITY")
        reasons.append(f"Liquidity ${last.liquidity:,.0f} is below the ${cfg.min_liquidity_usd:,.0f} floor.")
    elif (
        liquidity_baseline > 0
        and last.liquidity < liquidity_baseline * (1 - cfg.liquidity_deterioration_pct / 100)
    ):
        codes.append("LIQUIDITY_DETERIORATION")
        reasons.append(
            f"Liquidity fell from ${liquidity_baseline:,.0f} to ${last.liquidity:,.0f}."
        )

    if turnover < cfg.min_turnover_h1:
        codes.append("LOW_TURNOVER")
        reasons.append(f"One-hour turnover {turnover:.3f} is too low relative to liquidity.")

    if last.buys_h1 <= 0:
        codes.append("WEAK_ACTIVITY")
        reasons.append("No buy transactions in the last hour.")
    elif ratio < cfg.min_buy_sell_ratio:
        codes.append("WEAK_ACTIVITY")
        reasons.append(f"Buy/sell ratio {ratio:.2f} is below {cfg.min_buy_sell_ratio:.2f}.")
    elif ratio > cfg.max_buy_sell_ratio:
        codes.append("FOMO_ACTIVITY")
        reasons.append(f"Buy/sell ratio {ratio:.2f} is one-sided and likely artificial.")

    if not ctx.security_eligible or ctx.security_status == "FAIL":
        codes.append("SECURITY_GATE")
        reasons.append("Security checks do not permit an automatic entry.")
    elif ctx.critical_unknown > 0:
        codes.append("SECURITY_INCOMPLETE")
        reasons.append("Critical security information is missing; no automatic entry.")

    if ctx.score < cfg.entry_score_threshold:
        codes.append("LOW_SCORE")
        reasons.append(f"Opportunity score {ctx.score:.1f} is below {cfg.entry_score_threshold:.0f}.")
    if ctx.confidence < cfg.entry_confidence_threshold:
        codes.append("LOW_CONFIDENCE")
        reasons.append(
            f"Data confidence {ctx.confidence:.2f} is below {cfg.entry_confidence_threshold:.2f}."
        )

    if ctx.roundtrip_cost_pct > cfg.max_roundtrip_cost_pct:
        codes.append("HIGH_COST")
        reasons.append(
            f"Estimated round-trip cost {ctx.roundtrip_cost_pct:.2f}% exceeds "
            f"{cfg.max_roundtrip_cost_pct:.2f}%."
        )

    trend_component = clamp(h1_pct / max(cfg.trend_max_pct_h1, 0.1), 0.0, 1.0)
    band_mid = (cfg.pullback_min_pct + cfg.pullback_max_pct) / 2
    band_half = max((cfg.pullback_max_pct - cfg.pullback_min_pct) / 2, 0.1)
    pullback_component = clamp(1 - abs(drawdown - band_mid) / band_half, 0.0, 1.0)
    stabilization_component = clamp(1 - recent_band / max(cfg.stabilization_band_pct, 0.1), 0.0, 1.0)
    if recovery:
        stabilization_component = clamp(stabilization_component + 0.15, 0.0, 1.0)
    liquidity_component = clamp(last.liquidity / max(cfg.min_liquidity_usd * 4, 1), 0.0, 1.0)
    activity_component = clamp((ratio - 1) / max(cfg.max_buy_sell_ratio - 1, 0.1), 0.0, 1.0)

    strength = (
        0.25 * trend_component
        + 0.25 * pullback_component
        + 0.20 * stabilization_component
        + 0.15 * liquidity_component
        + 0.15 * activity_component
    )
    metrics["signal_strength"] = round(strength, 4)
    metrics["components"] = {
        "trend": round(trend_component, 3),
        "pullback": round(pullback_component, 3),
        "stabilization": round(stabilization_component, 3),
        "liquidity": round(liquidity_component, 3),
        "activity": round(activity_component, 3),
    }

    if strength < cfg.min_signal_strength:
        codes.append("LOW_SIGNAL")
        reasons.append(
            f"Signal strength {strength:.2f} is below {cfg.min_signal_strength:.2f}."
        )

    size_usd = min(ctx.available_cash, ctx.max_position_usd, cfg.max_position_usd)
    if size_usd < cfg.min_position_usd:
        codes.append("NO_EDGE")
        reasons.append(
            f"Available size ${size_usd:.2f} is below the ${cfg.min_position_usd:.2f} minimum."
        )

    if codes:
        return EntrySignal(
            action="REJECT",
            strength=round(strength, 4),
            reason_codes=list(dict.fromkeys(codes)),
            reasons=reasons,
            metrics=metrics,
            size_usd=round(size_usd, 4),
        )

    reasons.append(
        f"Uptrend {h1_pct:.1f}% with a {drawdown:.1f}% pullback, stabilised and liquid."
    )
    return EntrySignal(
        action="ENTER",
        strength=round(strength, 4),
        reason_codes=["ENTER"],
        reasons=reasons,
        metrics=metrics,
        size_usd=round(size_usd, 4),
    )

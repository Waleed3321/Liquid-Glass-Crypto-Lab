"""Opportunity scoring (0-100).

Weights follow the specification: liquidity 25, volume 20, buy/sell activity 15,
holder distribution 15, momentum quality 15, security completeness 10. The
function is pure so it can be unit-tested without a database; every component
returns an explanation string for the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import SecurityStatus
from app.strategies.indicators import clamp, log_slope, max_drawdown_pct, safe_div

WEIGHTS: dict[str, float] = {
    "liquidity": 25.0,
    "volume": 20.0,
    "activity": 15.0,
    "holders": 15.0,
    "momentum": 15.0,
    "security": 10.0,
}

_LIQUIDITY_POINTS = [
    (0.0, 0.0),
    (5_000.0, 0.0),
    (8_000.0, 8.0),
    (15_000.0, 14.0),
    (40_000.0, 19.0),
    (100_000.0, 22.0),
    (500_000.0, 25.0),
]

_VOLUME_POINTS = [
    (0.0, 0.0),
    (0.05, 2.0),
    (0.15, 6.0),
    (0.4, 11.0),
    (0.9, 16.0),
    (2.0, 20.0),
]

_MOMENTUM_POINTS = [
    (-30.0, 0.0),
    (-5.0, 1.0),
    (0.0, 3.0),
    (3.0, 7.0),
    (8.0, 11.0),
    (20.0, 13.5),
    (40.0, 14.0),
    (80.0, 10.0),
    (150.0, 4.0),
]


@dataclass(slots=True)
class ScoreInputs:
    liquidity_usd: float
    volume_h1: float
    volume_m5: float
    buys_h1: int
    sells_h1: int
    pct_h1: float
    pct_m5: float
    holder_concentration: float | None
    holder_count: int | None
    security_overall: str
    critical_pass: int
    critical_total: int
    providers_available: int
    providers_total: int
    snapshot_age_seconds: float
    history_points: int = 0
    prices: list[float] = field(default_factory=list)


@dataclass(slots=True)
class ScoredOpportunity:
    score: float
    confidence: float
    security_risk: float
    components: dict[str, float]
    explanations: list[str]
    rank_score: float

    def as_row(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "confidence": round(self.confidence, 4),
            "security_risk": round(self.security_risk, 2),
            "rank_score": round(self.rank_score, 4),
            "components": {k: round(v, 3) for k, v in self.components.items()},
            "explanations": self.explanations,
        }


def _interp(points: list[tuple[float, float]], value: float) -> float:
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if value <= x1:
            if x1 == x0:
                return y1
            ratio = (value - x0) / (x1 - x0)
            return y0 + (y1 - y0) * ratio
    return points[-1][1]


def _liquidity_component(liquidity: float) -> float:
    return clamp(_interp(_LIQUIDITY_POINTS, liquidity), 0.0, WEIGHTS["liquidity"])


def _volume_component(volume_h1: float, liquidity: float) -> float:
    turnover = safe_div(volume_h1, liquidity, 0.0)
    score = _interp(_VOLUME_POINTS, turnover)
    if volume_h1 < 1_000:
        score = min(score, 3.0)
    return clamp(score, 0.0, WEIGHTS["volume"])


def _activity_component(buys: int, sells: int) -> tuple[float, float, str]:
    total = buys + sells
    if total <= 0:
        return 0.0, 0.0, "No recent swap activity was observed."
    ratio = safe_div(buys, sells, float(buys) if sells == 0 else 1.0)
    balance = clamp(0.45 + 0.55 * min(ratio, 1.0 / ratio if ratio > 0 else 0.0), 0.0, 1.0)
    volume_factor = clamp(total / 150.0, 0.0, 1.0)
    score = WEIGHTS["activity"] * volume_factor * balance
    reason = (
        f"{buys} buys vs {sells} sells in the last hour "
        f"(ratio {ratio:.2f}, balance {balance:.2f})."
    )
    return score, ratio, reason


def _holders_component(top10: float | None, count: int | None) -> tuple[float, str]:
    if top10 is None:
        return 0.0, "Holder distribution is unavailable; no distribution points awarded."
    concentration = clamp(1.0 - max(0.0, top10 - 20.0) / 50.0, 0.0, 1.0)
    count_factor = clamp(count / 300.0, 0.35, 1.0) if count is not None else 0.6
    score = WEIGHTS["holders"] * concentration * count_factor
    reason = (
        f"Top 10 holders own {top10:.1f}%"
        + (f" across {count} holders" if count is not None else "")
        + f"; distribution factor {concentration * count_factor:.2f}."
    )
    return score, reason


def _momentum_component(inputs: ScoreInputs) -> tuple[float, str]:
    score = _interp(_MOMENTUM_POINTS, inputs.pct_h1)
    notes = [f"1h change {inputs.pct_h1:+.2f}%."]
    if inputs.pct_m5 > 15.0:
        score -= 6.0
        notes.append("Penalty: vertical 5-minute candle (spike chasing risk).")
    if inputs.pct_h1 > 150.0:
        score -= 4.0
        notes.append("Penalty: extreme 1-hour run-up.")
    if len(inputs.prices) >= 4:
        drawdown = -max_drawdown_pct(inputs.prices)
        if drawdown > 25.0:
            score -= 4.0
            notes.append(f"Penalty: {drawdown:.1f}% drawdown from the recent peak.")
        slope = log_slope(inputs.prices)
        if slope > 0.02:
            score += 1.5
            notes.append("Trend slope is positive across collected snapshots.")
        elif slope < -0.02:
            score -= 1.5
            notes.append("Trend slope is negative across collected snapshots.")
    return clamp(score, 0.0, WEIGHTS["momentum"]), " ".join(notes)


def _security_component(inputs: ScoreInputs) -> tuple[float, str]:
    if inputs.critical_total <= 0:
        return 0.0, "No critical security fields were evaluated."
    completion = clamp(inputs.critical_pass / inputs.critical_total, 0.0, 1.0)
    if inputs.security_overall == SecurityStatus.FAIL.value:
        completion = 0.0
    score = WEIGHTS["security"] * completion
    return score, (
        f"{inputs.critical_pass}/{inputs.critical_total} critical checks verified "
        f"(overall {inputs.security_overall})."
    )


def _confidence(inputs: ScoreInputs) -> float:
    age = max(0.0, inputs.snapshot_age_seconds)
    if age <= 60:
        freshness = 1.0
    elif age <= 120:
        freshness = 0.9
    elif age <= 300:
        freshness = 0.65
    elif age <= 600:
        freshness = 0.4
    else:
        freshness = 0.2

    # Confidence measures how much trustworthy data we have, not whether the
    # token is safe; safety is enforced separately through ``eligible``.
    security_factor = {
        SecurityStatus.PASS.value: 1.0,
        SecurityStatus.WARNING.value: 0.9,
        SecurityStatus.UNKNOWN.value: 0.55,
        SecurityStatus.UNAVAILABLE.value: 0.4,
        SecurityStatus.FAIL.value: 0.75,
    }.get(inputs.security_overall, 0.4)

    history_factor = 0.7 + 0.3 * clamp(inputs.history_points / 10.0, 0.0, 1.0)
    provider_factor = (
        clamp(inputs.providers_available / inputs.providers_total, 0.0, 1.0)
        if inputs.providers_total
        else 0.0
    )
    provider_factor = 0.6 + 0.4 * provider_factor
    return round(clamp(freshness * security_factor * history_factor * provider_factor, 0.0, 1.0), 4)


def compute_score(inputs: ScoreInputs, security_risk: float) -> ScoredOpportunity:
    liquidity = _liquidity_component(inputs.liquidity_usd)
    volume = _volume_component(inputs.volume_h1, inputs.liquidity_usd)
    activity, ratio, activity_reason = _activity_component(inputs.buys_h1, inputs.sells_h1)
    holders, holders_reason = _holders_component(inputs.holder_concentration, inputs.holder_count)
    momentum, momentum_reason = _momentum_component(inputs)
    security, security_reason = _security_component(inputs)

    components = {
        "liquidity": liquidity,
        "volume": volume,
        "activity": activity,
        "holders": holders,
        "momentum": momentum,
        "security": security,
    }
    score = clamp(sum(components.values()), 0.0, 100.0)
    confidence = _confidence(inputs)

    explanations = [
        f"Liquidity ${inputs.liquidity_usd:,.0f} scores {liquidity:.1f}/{WEIGHTS['liquidity']:.0f}.",
        (
            f"1h volume ${inputs.volume_h1:,.0f} "
            f"({safe_div(inputs.volume_h1, inputs.liquidity_usd) * 100:.1f}% of liquidity) "
            f"scores {volume:.1f}/{WEIGHTS['volume']:.0f}."
        ),
        f"Activity scores {activity:.1f}/{WEIGHTS['activity']:.0f}. {activity_reason}",
        f"Holders score {holders:.1f}/{WEIGHTS['holders']:.0f}. {holders_reason}",
        f"Momentum scores {momentum:.1f}/{WEIGHTS['momentum']:.0f}. {momentum_reason}",
        f"Security completeness scores {security:.1f}/{WEIGHTS['security']:.0f}. {security_reason}",
        f"Final score {score:.1f}/100 with confidence {confidence:.0%}.",
    ]
    if ratio > 4.0:
        explanations.append("Buy pressure is extremely one-sided; treat with caution.")

    return ScoredOpportunity(
        score=round(score, 2),
        confidence=confidence,
        security_risk=round(security_risk, 2),
        components=components,
        explanations=explanations,
        rank_score=round(score * confidence, 4),
    )

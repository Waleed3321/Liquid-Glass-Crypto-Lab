"""Small numeric helpers with no IO so they are trivially testable."""

from __future__ import annotations

import math
from collections.abc import Sequence


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if not denominator:
        return default
    return numerator / denominator


def sma(values: Sequence[float], window: int) -> float:
    if not values:
        return 0.0
    window = max(1, min(window, len(values)))
    subset = values[-window:]
    return sum(subset) / len(subset)


def pct_change(new: float, old: float) -> float:
    if old <= 0:
        return 0.0
    return (new - old) / old * 100.0


def log_slope(values: Sequence[float]) -> float:
    """Least-squares slope of log prices per step (a robust trend measure)."""
    points = [math.log(v) for v in values if v and v > 0]
    n = len(points)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(points) / n
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return 0.0
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, points, strict=True))
    return covariance / variance


def max_drawdown_pct(values: Sequence[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak * 100.0)
    return worst


def band_pct(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    low = min(values)
    high = max(values)
    if low <= 0:
        return 0.0
    return (high - low) / low * 100.0


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0

"""Snapshot retention: downsample older than 24h to hourly, prune beyond 7 days."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.config import settings
from app.core.logging import get_logger
from app.models import MarketSnapshot, OpportunityScore, StrategyDecision

logger = get_logger(__name__)


async def downsample_and_prune(session: AsyncSession) -> dict[str, int]:
    now = utc_now()
    raw_cutoff = now - timedelta(hours=settings.snapshot_raw_hours)
    full_cutoff = now - timedelta(days=settings.snapshot_full_days)

    rows = list(
        (
            await session.execute(
                select(MarketSnapshot)
                .where(MarketSnapshot.ts < raw_cutoff, MarketSnapshot.ts >= full_cutoff)
                .order_by(MarketSnapshot.pair_id, MarketSnapshot.ts)
            )
        )
        .scalars()
        .all()
    )
    keep: set[int] = set()
    grouped: dict[tuple[int, str], list[MarketSnapshot]] = defaultdict(list)
    for row in rows:
        bucket = row.ts.strftime("%Y-%m-%dT%H")
        grouped[(row.pair_id, bucket)].append(row)
    for bucket_rows in grouped.values():
        average_price = sum(float(r.price_usd) for r in bucket_rows) / len(bucket_rows)
        keep.add(min(bucket_rows, key=lambda r: abs(float(r.price_usd) - average_price)).id)

    drop_ids = [row.id for row in rows if row.id not in keep]
    for start in range(0, len(drop_ids), 400):
        chunk = drop_ids[start : start + 400]
        if chunk:
            await session.execute(delete(MarketSnapshot).where(MarketSnapshot.id.in_(chunk)))

    pruned_snapshots = (
        await session.execute(delete(MarketSnapshot).where(MarketSnapshot.ts < full_cutoff))
    ).rowcount or 0
    pruned_scores = (
        await session.execute(
            delete(OpportunityScore).where(OpportunityScore.ts < now - timedelta(days=5))
        )
    ).rowcount or 0
    pruned_decisions = (
        await session.execute(
            delete(StrategyDecision).where(StrategyDecision.created_at < now - timedelta(days=7))
        )
    ).rowcount or 0

    result = {
        "downsampled": len(drop_ids),
        "pruned_snapshots": int(pruned_snapshots),
        "pruned_scores": int(pruned_scores),
        "pruned_decisions": int(pruned_decisions),
    }
    logger.info("retention_complete", extra=result)
    return result

"""Background scanner loop (independent of any browser)."""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger

logger = get_logger(__name__)


async def run_loop(runner) -> None:
    """Run ticks until the runner is stopped. Failures never break the loop."""
    logger.info("scanner_loop_started", extra={"owner": runner.owner})
    while not runner.stopping:
        try:
            await runner.tick(source="loop")
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:  # noqa: BLE001
            logger.exception("scanner_loop_tick_failed")
        try:
            await asyncio.wait_for(runner.stopping_event.wait(), timeout=runner.interval_seconds)
        except TimeoutError:
            continue
    logger.info("scanner_loop_stopped")

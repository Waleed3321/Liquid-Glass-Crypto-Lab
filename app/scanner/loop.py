"""Background scanner loop (independent of any browser)."""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger

logger = get_logger(__name__)


async def run_loop(runner) -> None:
    """Run ticks until the runner is stopped. Failures never break the loop.

    Ticks are scheduled at a fixed cadence measured from the previous start, so
    time spent inside a slow tick does not push the next scan back by a full
    interval. A hung tick is cancelled by a hard timeout instead of stopping the
    scanner, which the product treats as a critical requirement.
    """
    logger.info("scanner_loop_started", extra={"owner": runner.owner})
    loop = asyncio.get_running_loop()
    while not runner.stopping:
        started = loop.time()
        try:
            await asyncio.wait_for(
                runner.tick(source="loop"), timeout=runner.tick_timeout_seconds
            )
        except TimeoutError:
            logger.warning(
                "scanner_tick_timeout", extra={"seconds": runner.tick_timeout_seconds}
            )
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:  # noqa: BLE001
            logger.exception("scanner_loop_tick_failed")
        delay = max(0.0, runner.interval_seconds - (loop.time() - started))
        try:
            await asyncio.wait_for(runner.stopping_event.wait(), timeout=delay)
        except TimeoutError:
            continue
    logger.info("scanner_loop_stopped")

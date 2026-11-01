"""Run exactly one scanner tick against the configured database.

Used by the local acceptance gate and by cloud cron jobs that prefer a
single explicit tick over waiting for the internal loop.

Usage::

    uv run python scripts/scan_once.py
    uv run python scripts/scan_once.py --source cron
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.init import init_database  # noqa: E402
from app.db.session import dispose_engine  # noqa: E402
from app.notifications.dispatcher import NotificationDispatcher  # noqa: E402
from app.providers.registry import build_providers  # noqa: E402
from app.scanner.runner import ScannerRunner  # noqa: E402
from app.services.events import EventHub  # noqa: E402


async def run_once(source: str) -> int:
    await init_database()
    providers = build_providers()
    hub = EventHub()
    dispatcher = NotificationDispatcher(providers.discord, hub)
    runner = ScannerRunner(providers, hub, dispatcher)
    try:
        await runner.startup()
        result = await runner.tick(source=source)
        print(json.dumps(result.as_dict(), indent=2, default=str))
        return 0 if result.status in {"COMPLETED", "DEGRADED"} else 1
    finally:
        await providers.close()
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="manual")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_once(args.source)))


if __name__ == "__main__":
    main()

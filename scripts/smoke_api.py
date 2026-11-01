"""Read-only smoke test against a running lab (local or deployed).

Usage::

    uv run python scripts/smoke_api.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json

import httpx

ENDPOINTS = [
    "/api/v1/health",
    "/api/v1/scanner/status",
    "/api/v1/scanner/runs?limit=5",
    "/api/v1/tokens?limit=5",
    "/api/v1/watchlist",
    "/api/v1/portfolio",
    "/api/v1/portfolio/performance?days=7",
    "/api/v1/paper-trades/history?limit=10",
    "/api/v1/strategies",
    "/api/v1/strategies/limits",
    "/api/v1/analytics",
    "/api/v1/notifications?limit=5",
    "/api/v1/settings",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    failures = 0
    with httpx.Client(base_url=base, timeout=args.timeout) as client:
        for path in ENDPOINTS:
            try:
                response = client.get(path)
            except httpx.HTTPError as exc:
                failures += 1
                print(f"FAIL {path} -> {exc.__class__.__name__}: {exc}")
                continue
            body = response.text[:160].replace("\n", " ")
            status = "ok" if response.status_code == 200 else "fail"
            if response.status_code != 200:
                failures += 1
            print(f"{status:4} {response.status_code} {path} {body}")

    print(json.dumps({"base": base, "failures": failures}), end="\n")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()

"""Live acceptance checklist for a deployed (or local) lab.

Every check runs against public HTTP endpoints only; nothing here needs the
developer's machine or database access.

Usage::

    uv run python scripts/verify_deploy.py --base https://lab.onrender.com
    uv run python scripts/verify_deploy.py --base https://... --admin-token-env ADMIN_TOKEN

Exit code is non-zero when a required check fails. Checks that genuinely
cannot run (for example a fourth-position probe without three open positions)
are reported as ``skip`` with the reason instead of pretending to pass.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta

import httpx

RESULTS: list[dict] = []


def record(name: str, status: str, detail: dict | str) -> None:
    RESULTS.append({"check": name, "status": status, "detail": detail})
    print(f"[{status}] {name}: {detail}")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def check_health(client: httpx.Client) -> dict:
    response = client.get("/api/v1/health")
    body = response.json()
    ok = (
        response.status_code == 200
        and body.get("status") == "ok"
        and body.get("database") == "ok"
        and body.get("paper_only") is True
    )
    record("health", "pass" if ok else "fail", {
        "status": body.get("status"),
        "database": body.get("database"),
        "paper_only": body.get("paper_only"),
        "scanner": (body.get("scanner") or {}).get("state"),
    })
    return body


def check_scanner(client: httpx.Client) -> dict:
    status = client.get("/api/v1/scanner/status").json()
    running = status.get("state") == "running"
    last_success = parse_ts(status.get("last_success_at"))
    fresh = last_success is not None and (
        datetime.now(UTC) - last_success < timedelta(minutes=10)
    )
    record("scanner-running", "pass" if running else "fail", {"state": status.get("state")})
    record("scanner-fresh", "pass" if fresh else "fail", {
        "last_success_at": status.get("last_success_at"),
        "next_scan_at": status.get("next_scan_at"),
    })
    return status


def check_cadence(client: httpx.Client) -> None:
    runs = client.get("/api/v1/scanner/runs?limit=10").json().get("runs", [])
    stamps = [parse_ts(run.get("started_at")) for run in runs]
    stamps = [stamp for stamp in stamps if stamp is not None]
    # Ordering from the API is not guaranteed; spacing is what matters here.
    gaps = [abs((a - b).total_seconds()) for a, b in zip(stamps, stamps[1:], strict=False)]
    closest = min(gaps) if gaps else None
    ok = closest is not None and closest <= 120
    record("scanner-cadence", "pass" if ok else "fail", {
        "runs": len(stamps),
        "closest_gap_seconds": closest,
    })


def check_account(client: httpx.Client) -> dict:
    portfolio = client.get("/api/v1/portfolio").json()
    initial = float(portfolio.get("initial_balance", 0))
    cash = float(portfolio.get("cash_balance", -1))
    open_positions = int(portfolio.get("open_positions", 99))
    ok = abs(initial - 10.0) < 1e-9 and cash >= 0 and open_positions <= 3
    record("paper-account", "pass" if ok else "fail", {
        "initial_balance": initial,
        "cash_balance": cash,
        "open_positions": open_positions,
        "equity": portfolio.get("equity"),
    })
    return portfolio


def check_limits(client: httpx.Client) -> dict:
    settings = client.get("/api/v1/settings").json()
    strategy = settings.get("strategy", {})
    locked = {
        "max_position_usd": float(strategy.get("max_position_usd", 99)) <= 2.5 + 1e-9,
        "max_open_positions": int(strategy.get("max_open_positions", 99)) <= 3,
        "daily_loss_limit_usd": float(strategy.get("daily_loss_limit_usd", 99)) <= 0.5 + 1e-9,
        "max_price_impact_pct": float(strategy.get("max_price_impact_pct", 99)) <= 1.0 + 1e-9,
    }
    ok = all(locked.values())
    record("hard-caps", "pass" if ok else "fail", locked)
    return settings


def check_discovery(client: httpx.Client) -> None:
    for chain in ("solana", "bsc"):
        payload = client.get(
            "/api/v1/tokens", params={"chain": chain, "window_hours": 6, "limit": 200}
        ).json()
        tokens = payload.get("tokens", [])
        too_old = [t for t in tokens if float(t.get("age_minutes") or 0) > 6 * 60 + 30]
        ok = bool(tokens) and not too_old
        record(f"discovery-{chain}", "pass" if ok else "fail", {
            "tokens": len(tokens),
            "outside_window": len(too_old),
        })


def check_sse(client: httpx.Client) -> None:
    seen = False
    try:
        with client.stream("GET", "/api/v1/stream", timeout=50.0) as response:
            if response.status_code != 200:
                record("sse-heartbeat", "fail", {"status": response.status_code})
                return
            for line in response.iter_lines():
                if "heartbeat" in line:
                    seen = True
                    break
    except httpx.HTTPError as exc:
        record("sse-heartbeat", "fail", {"error": str(exc)})
        return
    record("sse-heartbeat", "pass" if seen else "fail", {"heartbeat": seen})


def check_order_rejections(client: httpx.Client, portfolio: dict) -> None:
    headers = {}
    admin = os.environ.get("ADMIN_TOKEN")
    if admin:
        headers["X-Admin-Token"] = admin

    tokens = client.get("/api/v1/tokens", params={"limit": 1}).json().get("tokens", [])
    if not tokens:
        record("oversize-rejection", "skip", "no discovered tokens yet")
        return
    token_id = tokens[0]["id"]
    response = client.post(
        "/api/v1/paper-trades/buy",
        json={"token_id": token_id, "notional_usd": 3.0, "client_order_id": "verify-oversize"},
        headers=headers,
    )
    code = (response.json().get("error") or {}).get("code") if response.content else None
    ok = response.status_code == 409 and code == "POSITION_SIZE"
    record("oversize-rejection", "pass" if ok else "fail", {
        "status": response.status_code,
        "code": code,
    })

    open_positions = int(portfolio.get("open_positions", 0))
    if open_positions >= 3:
        response = client.post(
            "/api/v1/paper-trades/buy",
            json={"token_id": token_id, "notional_usd": 1.0, "client_order_id": "verify-slot"},
            headers=headers,
        )
        code = (response.json().get("error") or {}).get("code") if response.content else None
        record("fourth-position-rejection", "pass" if code == "MAX_POSITIONS" else "fail", {
            "status": response.status_code,
            "code": code,
        })
    else:
        record("fourth-position-rejection", "skip", {
            "reason": "needs three open positions",
            "open_positions": open_positions,
        })


def check_dashboard(client: httpx.Client) -> None:
    try:
        response = client.get("/")
    except httpx.HTTPError as exc:
        record("dashboard", "fail", {"error": str(exc)})
        return
    html = response.text
    served = response.status_code == 200 and "Liquid Glass" in html
    record("dashboard-shell", "pass" if served else "skip", {
        "status": response.status_code,
        "served_by_api": served,
        "note": None if served else "API host does not serve the dashboard; check the static host instead",
    })
    config = client.get("/config.js")
    if config.status_code == 200:
        text = config.text.lower()
        leaked = "discord" in text or "webhook" in text or "token" in text
        record("frontend-secrets", "pass" if not leaked else "fail", {"leaked": leaked})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="API origin, e.g. https://lab.onrender.com")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    with httpx.Client(base_url=base, timeout=args.timeout, follow_redirects=True) as client:
        check_health(client)
        check_scanner(client)
        check_cadence(client)
        portfolio = check_account(client)
        check_limits(client)
        check_discovery(client)
        check_sse(client)
        check_order_rejections(client, portfolio)
        check_dashboard(client)

    failures = [row for row in RESULTS if row["status"] == "fail"]
    skips = [row for row in RESULTS if row["status"] == "skip"]
    print(json.dumps({
        "base": base,
        "passed": len(RESULTS) - len(failures) - len(skips),
        "failed": len(failures),
        "skipped": len(skips),
    }))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()

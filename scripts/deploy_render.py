"""Create (or update) the single Render web service from local env variables.

All credentials are read from environment variables or a local ``.deploy.env``
file that is git-ignored. Nothing is echoed: the script prints env-var *names*
and never their values.

Required for a first deploy::

    RENDER_API_KEY       Render account API key
    GITHUB_REPO          owner/name of the public repository Render builds from
    DATABASE_URL         Neon pooled Postgres URL (sslmode=require)

Optional::

    DATABASE_URL_UNPOOLED  Neon direct URL for Alembic (falls back to DATABASE_URL)
    DISCORD_WEBHOOK_URL  enables Discord notifications
    CORS_ORIGINS         dashboard origin, e.g. https://lab.qodersites.com
    SCANNER_TICK_TOKEN   shared secret for POST /api/v1/scanner/tick
    ADMIN_TOKEN          protects mutating settings/scanner endpoints

Usage::

    uv run python scripts/deploy_render.py --dry-run
    uv run python scripts/deploy_render.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

API = "https://api.render.com/v1"
ROOT = Path(__file__).resolve().parents[1]
SERVICE_NAME = "liquid-glass-crypto-lab"
BRANCH = "main"

OPTIONAL_KEYS = (
    "DATABASE_URL_UNPOOLED",
    "DISCORD_WEBHOOK_URL",
    "CORS_ORIGINS",
    "SCANNER_TICK_TOKEN",
    "ADMIN_TOKEN",
    "SOL_PRICE_USD",
    "BNB_PRICE_USD",
)


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_vars(require_secrets: bool = True) -> list[dict[str, str]]:
    required = ("RENDER_API_KEY", "GITHUB_REPO", "DATABASE_URL")
    missing = [key for key in required if not os.environ.get(key)]
    if missing and require_secrets:
        raise SystemExit(f"Missing environment variables: {', '.join(missing)}")

    values = {
        "APP_ENV": "production",
        "LOG_LEVEL": "INFO",
        "DATABASE_URL": os.environ.get("DATABASE_URL", "<missing>"),
        "SCANNER_ENABLED": "true",
        "SCAN_INTERVAL_SECONDS": "60",
        "DISCOVERY_WINDOW_HOURS": "6",
        "MIN_TICK_GAP_SECONDS": "45",
        "LEASE_TTL_SECONDS": "300",
        "DISCORD_ENABLED": "true",
        "SOL_PRICE_USD": "150",
        "BNB_PRICE_USD": "600",
    }
    for key in OPTIONAL_KEYS:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return [{"key": key, "value": value} for key, value in values.items()]


def api(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    response = client.request(method, f"{API}{path}", **kwargs)
    if response.status_code >= 300:
        raise SystemExit(f"Render API {method} {path} failed ({response.status_code}): {response.text[:400]}")
    return response


def find_service(client: httpx.Client, owner_id: str) -> dict | None:
    response = api(client, "GET", f"/services?name={SERVICE_NAME}&ownerId={owner_id}&limit=20")
    for entry in response.json():
        service = entry.get("service", entry)
        if service.get("name") == SERVICE_NAME:
            return service
    return None


def wait_for_deploy(client: httpx.Client, service_id: str, timeout_seconds: int = 1200) -> dict:
    deadline = time.time() + timeout_seconds
    last = ""
    while time.time() < deadline:
        service = api(client, "GET", f"/services/{service_id}").json()
        detail = service.get("serviceDetails") or {}
        deploy = service.get("deploy") or {}
        state = detail.get("healthCheckStatus") or deploy.get("status") or "unknown"
        if state != last:
            print(f"deploy state: {state}")
            last = state
        if state in {"live", "healthy"}:
            return service
        if deploy.get("status") in {"build_failed", "update_failed", "canceled", "deactivated"}:
            raise SystemExit(f"Deploy failed: {deploy.get('status')}")
        time.sleep(15)
    raise SystemExit("Timed out waiting for the deploy to go live.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(ROOT / ".deploy.env"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    variables = env_vars(require_secrets=not args.dry_run)
    names = sorted(item["key"] for item in variables)

    if args.dry_run:
        print(json.dumps({"service": SERVICE_NAME, "branch": BRANCH, "env_keys": names}, indent=2))
        return

    headers = {"Authorization": f"Bearer {os.environ['RENDER_API_KEY']}", "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=60.0) as client:
        owners = api(client, "GET", "/owners?limit=1").json()
        if not owners:
            raise SystemExit("No Render owner found for this API key.")
        owner_id = (owners[0].get("owner") or {}).get("id")

        existing = find_service(client, owner_id)
        if existing:
            service_id = existing["id"]
            print(f"updating existing service {service_id}")
            api(client, "PUT", f"/services/{service_id}/env-vars", json=variables)
            deploy = api(client, "POST", f"/services/{service_id}/deploys", json={}).json()
            print(f"deploy {deploy.get('id')} started")
        else:
            payload = {
                "type": "web_service",
                "name": SERVICE_NAME,
                "ownerId": owner_id,
                "repo": f"https://github.com/{os.environ['GITHUB_REPO']}",
                "branch": BRANCH,
                "autoDeploy": "yes",
                "serviceDetails": {
                    "runtime": "docker",
                    "plan": "free",
                    "region": "oregon",
                    "healthCheckPath": "/api/v1/health",
                    "envSpecificDetails": {
                        "dockerfilePath": "./Dockerfile",
                        "dockerContext": ".",
                    },
                    "envVars": variables,
                },
            }
            created = api(client, "POST", "/services", json=payload).json()
            service_id = created.get("id") or (created.get("service") or {}).get("id")
            print(f"created service {service_id}")

        service = wait_for_deploy(client, service_id, timeout_seconds=args.timeout)
        url = (service.get("serviceDetails") or {}).get("url")
        print(json.dumps({"service_id": service_id, "url": url}, indent=2))
        if not url:
            print("Service is live but no URL was returned yet; check the Render dashboard.", file=sys.stderr)


if __name__ == "__main__":
    main()

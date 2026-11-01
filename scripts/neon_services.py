"""Prove every provisioned Neon service is reachable with the injected env vars.

Run after ``neon deploy``::

    python scripts/neon_services.py            # all checks
    python scripts/neon_services.py --only storage,realtime

The app itself only consumes Postgres: it is a single-user paper-trading lab
with its own SSE stream, no sign-in, no uploads and no serverless functions.
The remaining services are therefore verified at the service level from this
script instead of being wired into request paths that would not use them.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ENV_FILE = ROOT / ".env.local"
BUCKET = "assets"
REGION, SERVICE = "s3", "s3"


def _env() -> dict[str, str]:
    """``neon deploy`` writes .env.local; OS env wins over the file."""
    values = {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None}
    values.update({k: v for k, v in os.environ.items() if k in values or k.startswith(("AWS_", "NEON_"))})
    return values


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    key = _hmac(f"AWS4{secret}".encode(), date)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    return key


def _s3(method: str, endpoint: str, path: str, body: bytes = b"") -> tuple[int, bytes]:
    """Signed path-style S3 request (Neon storage accepts SigV4 + path style only)."""
    creds = _env()
    access, secret = creds["AWS_ACCESS_KEY_ID"], creds["AWS_SECRET_ACCESS_KEY"]
    region = creds.get("AWS_REGION") or "us-east-2"
    parts = urlsplit(endpoint)
    uri = quote(f"{parts.path.rstrip('/')}{path}", safe="/-_.~")
    payload_hash = hashlib.sha256(body).hexdigest()
    now = datetime.now(UTC)
    amz_date, date = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_headers = (
        f"host:{parts.netloc}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    canonical_request = "\n".join(
        [method, uri, "", canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{date}/{region}/{SERVICE}/aws4_request"
    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signature = hmac.new(_signing_key(secret, date, region, SERVICE), to_sign.encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(f"{parts.scheme}://{parts.netloc}{uri}", data=body or None, method=method)
    request.add_header(
        "Authorization",
        f"AWS4-HMAC-SHA256 Credential={access}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}",
    )
    request.add_header("x-amz-content-sha256", payload_hash)
    request.add_header("x-amz-date", amz_date)
    if body:
        request.add_header("Content-Type", "text/plain")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _http(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _kill_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        process.terminate()


async def check_database() -> dict:
    from sqlalchemy import text

    from app.core.config import settings
    from app.db.session import dispose_engine, get_engine

    engine = get_engine()
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("select version()"))).scalar()
            tables = (
                await conn.execute(
                    text("select count(*) from pg_tables where schemaname = 'public'")
                )
            ).scalar()
            revision = (await conn.execute(text("select version_num from alembic_version"))).scalar()
    finally:
        await dispose_engine()
    return {
        "ok": True,
        "endpoint": urlsplit(settings.normalized_database_url).hostname,
        "pooled": settings.is_pooled,
        "migration_endpoint": urlsplit(settings.migration_database_url).hostname,
        "server": version.split(" on ")[0],
        "tables": tables,
        "revision": revision,
    }


def check_storage() -> dict:
    env = _env()
    endpoint = env["AWS_ENDPOINT_URL_S3"]
    key = f"healthcheck/{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}.txt"
    payload = b"liquid glass neon storage check\n"
    status, _ = _s3("PUT", endpoint, f"/{BUCKET}/{key}", payload)
    if status not in (200, 201):
        raise RuntimeError(f"PUT {BUCKET}/{key} -> HTTP {status}")
    status, body = _s3("GET", endpoint, f"/{BUCKET}/{key}")
    if status != 200 or body != payload:
        raise RuntimeError(f"GET {BUCKET}/{key} -> HTTP {status}, body mismatch={body != payload}")
    status, _ = _s3("DELETE", endpoint, f"/{BUCKET}/{key}")
    if status not in (200, 204):
        raise RuntimeError(f"DELETE {BUCKET}/{key} -> HTTP {status}")
    return {"ok": True, "bucket": BUCKET, "object": key, "roundtrip": "put/get/delete"}


def check_function() -> dict:
    env = _env()
    status, body = _http(env["NEON_FUNCTION_HELLO_BASE_URL"])
    text = body.decode(errors="replace").strip()
    if status != 200 or not text:
        raise RuntimeError(f"hello function -> HTTP {status} {text[:120]!r}")
    return {"ok": True, "status": status, "body": text}


def check_auth() -> dict:
    env = _env()
    status, body = _http(env["NEON_AUTH_JWKS_URL"])
    if status != 200:
        raise RuntimeError(f"jwks -> HTTP {status}")
    keys = json.loads(body).get("keys") or []
    if not keys:
        raise RuntimeError("jwks returned no signing keys")
    return {
        "ok": True,
        "base_url": urlsplit(env["NEON_AUTH_BASE_URL"]).hostname,
        "algorithms": sorted({key.get("alg", "?") for key in keys}),
        "keys": len(keys),
    }


def check_realtime() -> dict:
    """Run a real live query through the official CLI client.

    Realtime speaks a beta WebSocket protocol, so the supported way to exercise
    it outside a JS app is ``neon realtime subscribe``; we take the initial
    snapshot event and stop.
    """
    env = _env()
    url = env["NEON_REALTIME_URL"]
    if not url.startswith("wss://"):
        raise RuntimeError(f"NEON_REALTIME_URL is not a WebSocket URL: {url[:12]}…")
    query = "select count(*)::int as rows from tokens"
    neon = shutil.which("neon")
    if not neon:
        raise RuntimeError("neon CLI not found on PATH")
    command = [neon, "realtime", "subscribe", query, "-o", "json"]
    if os.name == "nt" and neon.lower().endswith((".cmd", ".bat")):
        command = ["cmd", "/c", *command]

    # The subscription never exits on its own. Write to a file (a pipe would
    # block once the killed shell's child keeps it open) and kill the tree.
    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False) as handle:
        path = handle.name
    with open(path, "w", encoding="utf-8") as output_file:
        process = subprocess.Popen(command, stdout=output_file, stderr=subprocess.DEVNULL)
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            pass
        finally:
            if process.poll() is None:
                _kill_tree(process)
                process.wait(timeout=10)
    with open(path, encoding="utf-8") as handle:
        output = handle.read()
    Path(path).unlink(missing_ok=True)
    snapshot = next(
        (
            event["rows"]
            for event in (json.loads(line) for line in output.splitlines() if line.startswith("{"))
            if event.get("type") == "snapshot"
        ),
        None,
    )
    if snapshot is None:
        raise RuntimeError(f"no snapshot from `neon realtime subscribe`: {output[:160]!r}")
    return {
        "ok": True,
        "endpoint": urlsplit(url).hostname,
        "query": query,
        "snapshot": snapshot,
        "secret_present": bool(env.get("NEON_REALTIME_SECRET")),
    }


CHECKS = {
    "database": check_database,
    "storage": check_storage,
    "function": check_function,
    "auth": check_auth,
    "realtime": check_realtime,
}


async def main_async(names: list[str]) -> int:
    failures = 0
    for name in names:
        try:
            result = await CHECKS[name]() if asyncio.iscoroutinefunction(CHECKS[name]) else CHECKS[name]()
            print(json.dumps({"service": name, **result}))
        except Exception as error:  # noqa: BLE001 - a check failure is the report
            failures += 1
            print(json.dumps({"service": name, "ok": False, "error": f"{type(error).__name__}: {error}"}))
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        default=",".join(CHECKS),
        help=f"comma separated subset of {','.join(CHECKS)}",
    )
    args = parser.parse_args()
    names = [name.strip() for name in args.only.split(",") if name.strip()]
    unknown = sorted(set(names) - set(CHECKS))
    if unknown:
        parser.error(f"unknown checks: {', '.join(unknown)}")
    sys.exit(asyncio.run(main_async(names)))


if __name__ == "__main__":
    main()

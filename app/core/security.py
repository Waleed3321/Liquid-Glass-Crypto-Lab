"""Security helpers.

The platform is paper-only: nothing in this module (or anywhere else in the
codebase) signs transactions, touches wallets, or stores private keys.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Header, HTTPException, Request

from app.core.config import settings


def constant_time_equals(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left.encode(), right.encode())


def generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def mask_secret(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-2:]}"


def fingerprint(value: str | None) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:12]


class AdminGuard:
    """Optional admin token for mutating endpoints.

    When ``ADMIN_TOKEN`` is unset the lab is intentionally open (paper money
    only). When set, every mutating route requires ``X-Admin-Token``.
    """

    async def __call__(self, request: Request, x_admin_token: str | None = Header(default=None)) -> None:
        expected = settings.admin_token
        if not expected:
            return
        if not x_admin_token or not constant_time_equals(x_admin_token, expected):
            raise HTTPException(status_code=401, detail="Admin token required")


require_admin = AdminGuard()

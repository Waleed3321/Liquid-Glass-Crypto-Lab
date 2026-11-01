"""Application error contract.

Every failure returned to the browser has the same shape::

    {"error": {"code": "MAX_POSITIONS", "message": "...", "details": {...},
               "request_id": "..."}}
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class RiskLimitError(AppError):
    """Raised when a paper order violates a hard risk rule."""

    status_code = 409
    code = "RISK_LIMIT"


class ProviderError(AppError):
    status_code = 503
    code = "PROVIDER_ERROR"


class RateLimitedError(ProviderError):
    status_code = 429
    code = "RATE_LIMITED"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# Stable rejection codes used by trading and scanner decisions
# ---------------------------------------------------------------------------
REASON_MAX_POSITIONS = "MAX_POSITIONS"
REASON_POSITION_SIZE = "POSITION_SIZE"
REASON_INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
REASON_DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
REASON_IMPACT_LIMIT = "IMPACT_LIMIT"
REASON_STALE_DATA = "STALE_DATA"
REASON_SECURITY_REJECTED = "SECURITY_REJECTED"
REASON_SECURITY_INCOMPLETE = "SECURITY_INCOMPLETE"
REASON_SECURITY_WARNINGS = "SECURITY_WARNINGS"
REASON_DUPLICATE_ORDER = "DUPLICATE_ORDER"
REASON_NO_POSITION = "NO_POSITION"
REASON_QUANTITY = "INVALID_QUANTITY"
REASON_SCANNER_BUSY = "SCANNER_BUSY"
REASON_TICK_UNAUTHORIZED = "TICK_UNAUTHORIZED"

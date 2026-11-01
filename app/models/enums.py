"""String enums shared by models, schemas and services."""

from __future__ import annotations

from enum import StrEnum


class Chain(StrEnum):
    SOLANA = "solana"
    BSC = "bsc"

    @property
    def label(self) -> str:
        return {"solana": "Solana", "bsc": "BNB Chain"}[self.value]


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    NEW = "NEW"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"


class SecurityStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class DecisionAction(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    HOLD = "HOLD"
    REJECT = "REJECT"


class NotificationKind(StrEnum):
    HIGH_SCORE_TOKEN = "HIGH_SCORE_TOKEN"
    SECURITY_FAILURE = "SECURITY_FAILURE"
    SECURITY_WARNING = "SECURITY_WARNING"
    TRADE_ENTRY = "TRADE_ENTRY"
    PARTIAL_PROFIT = "PARTIAL_PROFIT"
    FULL_EXIT = "FULL_EXIT"
    STOP_LOSS = "STOP_LOSS"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    SCANNER_FAILURE = "SCANNER_FAILURE"
    SCANNER_RECOVERY = "SCANNER_RECOVERY"
    SERVICE_HEALTH = "SERVICE_HEALTH"
    TEST = "TEST"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ScannerRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    SKIPPED = "SKIPPED"


class Severity(StrEnum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

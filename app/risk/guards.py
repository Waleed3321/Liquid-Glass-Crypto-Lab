"""Hard risk guards. Every check raises a stable, user-facing rejection code."""

from __future__ import annotations

from decimal import Decimal

from app.core.errors import (
    REASON_DAILY_LOSS_LIMIT,
    REASON_INSUFFICIENT_BALANCE,
    REASON_MAX_POSITIONS,
    REASON_POSITION_SIZE,
    REASON_SECURITY_INCOMPLETE,
    REASON_SECURITY_REJECTED,
    REASON_SECURITY_WARNINGS,
    RiskLimitError,
)
from app.execution.quote import Quote
from app.models import PaperAccount
from app.models.enums import SecurityStatus
from app.risk.daily_loss import loss_limit_reached
from app.risk.limits import RiskLimits
from app.services.security import SecurityAssessment


def check_open_slots(open_count: int, limits: RiskLimits) -> None:
    if open_count >= limits.max_open_positions:
        raise RiskLimitError(
            f"Maximum of {limits.max_open_positions} open positions reached.",
            code=REASON_MAX_POSITIONS,
            details={"open_positions": open_count, "max_open_positions": limits.max_open_positions},
        )


def check_position_size(notional_usd: float, limits: RiskLimits) -> None:
    if notional_usd <= 0:
        raise RiskLimitError("Order size must be positive.", code=REASON_POSITION_SIZE)
    if notional_usd > limits.max_position_usd + 1e-9:
        raise RiskLimitError(
            f"Position size exceeds the ${limits.max_position_usd:.2f} cap.",
            code=REASON_POSITION_SIZE,
            details={"requested": notional_usd, "max_position_usd": limits.max_position_usd},
        )


def check_cash(account: PaperAccount, cash_debit: float) -> None:
    cash = Decimal(str(account.cash_balance))
    if cash < Decimal(str(cash_debit)):
        raise RiskLimitError(
            f"Insufficient paper balance: need ${cash_debit:.2f}, have ${cash:.2f}.",
            code=REASON_INSUFFICIENT_BALANCE,
            details={"required": cash_debit, "cash_balance": float(cash)},
        )


def check_daily_loss(daily, limits: RiskLimits) -> None:
    if loss_limit_reached(daily, limits.daily_loss_limit_usd):
        raise RiskLimitError(
            f"Daily loss limit of ${limits.daily_loss_limit_usd:.2f} reached; new entries are halted until the next trading day.",
            code=REASON_DAILY_LOSS_LIMIT,
            details={
                "realized_pnl": float(daily.realized_pnl) if daily else 0.0,
                "limit": limits.daily_loss_limit_usd,
            },
        )


def check_security(assessment: SecurityAssessment | None) -> None:
    if assessment is None:
        raise RiskLimitError(
            "No security data is available for this token.", code=REASON_SECURITY_INCOMPLETE
        )
    if assessment.overall == SecurityStatus.FAIL.value:
        raise RiskLimitError(
            assessment.summary(), code=REASON_SECURITY_REJECTED, details={"reasons": assessment.reasons}
        )
    if not assessment.eligible:
        code = (
            REASON_SECURITY_INCOMPLETE
            if assessment.overall in {SecurityStatus.UNKNOWN.value, SecurityStatus.UNAVAILABLE.value}
            else REASON_SECURITY_WARNINGS
        )
        raise RiskLimitError(
            assessment.summary(), code=code, details={"reasons": assessment.reasons}
        )
    if not (assessment.buy_tax_known and assessment.sell_tax_known):
        raise RiskLimitError(
            "Token taxes are unknown; automatic entry is blocked.",
            code=REASON_SECURITY_INCOMPLETE,
            details={"reasons": ["Buy/sell tax data unavailable from the security provider"]},
        )


def check_quote(quote: Quote) -> None:
    if not quote.ok:
        raise RiskLimitError(
            quote.reject_reason or "Simulated quote rejected.",
            code=quote.reject_code or "QUOTE_REJECTED",
            details=quote.as_dict(),
        )

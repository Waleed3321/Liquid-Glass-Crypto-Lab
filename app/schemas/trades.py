"""Trading request models. All limits are also enforced server-side."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class BuyRequestIn(BaseModel):
    token_id: int = Field(gt=0)
    notional_usd: float | None = Field(default=None, gt=0, le=1000)
    client_order_id: str | None = Field(default=None, max_length=96)

    @field_validator("client_order_id")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class SellRequestIn(BaseModel):
    position_id: int = Field(gt=0)
    ratio: float | None = Field(default=None, gt=0, le=1)
    qty: float | None = Field(default=None, gt=0)
    exit_key: str | None = Field(default=None, max_length=120)

    @field_validator("qty")
    @classmethod
    def _exclusive(cls, value: float | None) -> float | None:
        return value

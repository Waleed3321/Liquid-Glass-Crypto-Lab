"""Watchlist request models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WatchlistIn(BaseModel):
    token_id: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=280)

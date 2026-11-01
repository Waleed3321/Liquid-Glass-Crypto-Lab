"""Shared API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel):
    total: int
    limit: int
    offset: int

"""
Shared Pydantic schemas used across the entire API surface.

BaseResponse         — single-object API envelope
PaginatedResponse    — list with pagination metadata
ErrorDetail          — structured error body
ErrorResponse        — top-level error envelope
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """
    Base Pydantic model that:
    - Accepts both snake_case (first_name) and camelCase (firstName) on input.
    - Serialises to camelCase on output (OpenAPI / JSON responses).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,  # allow snake_case input alongside the alias
        from_attributes=True,
    )


# ── Timestamps mixin ───────────────────────────────────────────────────────
class TimestampSchema(CamelModel):
    id: UUID
    created_at: datetime
    updated_at: datetime


# ── Envelope wrappers ──────────────────────────────────────────────────────
class BaseResponse(CamelModel, Generic[T]):
    """Standard single-item response envelope."""

    data: T
    message: str = "Success"


class PaginationMeta(CamelModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_next: bool
    has_previous: bool


class PaginatedResponse(CamelModel, Generic[T]):
    """Standard paginated list response envelope."""

    data: list[T]
    pagination: PaginationMeta
    message: str = "Success"


# ── Error schemas ──────────────────────────────────────────────────────────
class ErrorDetail(CamelModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(CamelModel):
    """Top-level error envelope — mirrors exception_handlers output."""

    error: ErrorDetail

"""
Security module Pydantic schemas.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.shared.base_schemas import CamelModel, PaginationMeta


# ── Login attempts ───────────────────────────────────────────────────────

class LoginAttemptResponse(CamelModel):
    id: UUID
    user_id: UUID | None = None
    email: str | None = None
    ip_address: str
    user_agent: str | None = None
    method: str
    is_success: bool | None = None
    failure_reason: str | None = None
    attempted_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("ip_address", mode="before")
    @classmethod
    def coerce_ip_to_str(cls, v: object) -> str:
        return str(v)


class LoginAttemptListResponse(CamelModel):
    attempts: list[LoginAttemptResponse]
    pagination: PaginationMeta


# ── Blocked IPs ──────────────────────────────────────────────────────────

class BlockIPRequest(CamelModel):
    ip_address: str = Field(..., description="IPv4 or IPv6 address to block")
    reason: str | None = None
    hours: int | None = Field(
        None, ge=1, le=8760, description="Block duration in hours; omit for permanent"
    )


class BlockedIPResponse(CamelModel):
    id: UUID
    ip_address: str
    reason: str | None = None
    blocked_by: UUID | None = None
    blocked_until: datetime | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("ip_address", mode="before")
    @classmethod
    def coerce_ip_to_str(cls, v: object) -> str:
        return str(v)


class BlockedIPListResponse(CamelModel):
    blocked_ips: list[BlockedIPResponse]
    pagination: PaginationMeta


# ── Security events ──────────────────────────────────────────────────────

class SecurityEventResponse(CamelModel):
    """Aggregated suspicious-activity event for dashboard display."""

    ip_address: str
    failure_count: int
    first_seen: datetime
    last_seen: datetime
    is_blocked: bool
    emails_targeted: list[str]

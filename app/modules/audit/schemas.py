"""
Audit module Pydantic schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.shared.base_schemas import CamelModel, PaginationMeta


# ── Response schemas ────────────────────────────────────────────────────

class AuditLogResponse(CamelModel):
    id: UUID
    organization_id: UUID | None = None
    actor_user_id: UUID | None = None
    actor_type: str
    action: str
    resource_type: str | None = None
    resource_id: UUID | None = None
    old_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    description: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("ip_address", mode="before")
    @classmethod
    def coerce_ip_to_str(cls, v: Any) -> str | None:
        return str(v) if v is not None else None


class AuditLogDetailResponse(AuditLogResponse):
    """Single log entry that includes a field-level diff view."""

    # diff is computed by the service and injected here
    diff: dict[str, dict[str, Any]] = Field(default_factory=dict)


class AuditLogListResponse(CamelModel):
    logs: list[AuditLogResponse]
    pagination: PaginationMeta

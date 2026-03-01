"""
API Management Pydantic schemas.

API Keys:
  CreateKeyRequest / CreateKeyResponse / APIKeyResponse / APIKeyListResponse

Webhooks:
  CreateWebhookRequest / UpdateWebhookRequest / WebhookResponse /
  WebhookListResponse / WebhookDeliveryResponse / WebhookDeliveryListResponse
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AnyHttpUrl, Field, field_validator

from app.shared.base_schemas import CamelModel, PaginationMeta


# ── API Key schemas ──────────────────────────────────────────────────────────

class CreateKeyRequest(CamelModel):
    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    expires_at: datetime | None = None


class CreateKeyResponse(CamelModel):
    """
    Returned once at creation. ``key`` is the raw secret — never stored, never
    shown again.
    """

    id: UUID
    key: str = Field(description="Full raw key  — shown only once at creation")
    prefix: str = Field(description="First 10 chars used for identification")
    name: str
    scopes: list[str]
    rate_limit_per_minute: int
    expires_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class APIKeyResponse(CamelModel):
    """Safe representation — no raw key, no hash."""

    id: UUID
    organization_id: UUID
    created_by: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    rate_limit_per_minute: int
    is_active: bool
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("last_used_ip", mode="before")
    @classmethod
    def coerce_ip_to_str(cls, v: Any) -> str | None:
        return str(v) if v is not None else None


class APIKeyListResponse(CamelModel):
    keys: list[APIKeyResponse]
    pagination: PaginationMeta


# ── Webhook schemas ─────────────────────────────────────────────────────────

class CreateWebhookRequest(CamelModel):
    url: AnyHttpUrl
    events: list[str] = Field(..., min_length=1)
    name: str | None = Field(None, max_length=255)


class UpdateWebhookRequest(CamelModel):
    url: AnyHttpUrl | None = None
    events: list[str] | None = None
    name: str | None = Field(None, max_length=255)
    is_active: bool | None = None


class WebhookResponse(CamelModel):
    id: UUID
    organization_id: UUID
    created_by: UUID
    url: str
    events: list[str]
    is_active: bool
    failure_count: int
    last_failure_reason: str | None = None
    last_triggered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreateWebhookResponse(WebhookResponse):
    """Extends WebhookResponse with the signing secret (shown once)."""

    signing_secret: str = Field(
        description="HMAC-SHA256 signing secret — shown only at creation"
    )


class WebhookListResponse(CamelModel):
    webhooks: list[WebhookResponse]
    pagination: PaginationMeta


# ── Webhook Delivery schemas ────────────────────────────────────────────────

class WebhookDeliveryResponse(CamelModel):
    id: UUID
    webhook_id: UUID
    event: str
    payload: dict[str, Any]
    response_status: int | None = None
    response_body: str | None = None
    response_time_ms: int | None = None
    status: str
    attempts: int
    next_retry_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookDeliveryListResponse(CamelModel):
    deliveries: list[WebhookDeliveryResponse]
    pagination: PaginationMeta

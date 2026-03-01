"""
Feature module Pydantic schemas.

FeatureCheckResult      — single feature check outcome
FeatureResponse         — feature definition
PlanFeatureResponse     — feature assigned to a plan
OverrideResponse        — org-level feature override
Request/response shapes for all 6 endpoints.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.shared.base_schemas import CamelModel


# ── Check schemas ─────────────────────────────────────────────────────────

class FeatureCheckResult(CamelModel):
    feature_key: str
    enabled: bool
    limit: int | None = None          # None = unlimited; 0 = disabled


class MultiCheckRequest(CamelModel):
    """Body sent to POST /features/check (accept multiple keys at once)."""
    keys: list[str] = Field(..., min_length=1)


class MultiCheckResponse(CamelModel):
    results: dict[str, FeatureCheckResult]


# ── Feature definition schemas ────────────────────────────────────────────

class FeatureResponse(CamelModel):
    id: UUID
    key: str
    name: str | None = None
    description: str | None = None
    module: str | None = None
    created_at: datetime
    updated_at: datetime


class FeatureListResponse(CamelModel):
    features: list[FeatureResponse]
    total: int


class CreateFeatureRequest(CamelModel):
    key: str = Field(..., min_length=2, max_length=150, pattern=r"^[a-z0-9_.:-]+$")
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=1000)
    module: str | None = Field(None, max_length=100)


# ── Plan-feature schemas ──────────────────────────────────────────────────

class AssignPlanFeatureRequest(CamelModel):
    feature_id: UUID
    limit_value: int | None = Field(
        None,
        ge=0,
        description="null = boolean flag (unlimited); set to enforce a numeric quota",
    )


class PlanFeatureResponse(CamelModel):
    plan_id: UUID
    feature_id: UUID
    feature_key: str
    feature_name: str | None = None
    limit_value: int | None = None
    created_at: datetime


# ── Override schemas ──────────────────────────────────────────────────────

class GrantOverrideRequest(CamelModel):
    feature_id: UUID
    enabled: bool = True
    limit_value: int | None = Field(
        None,
        ge=0,
        description="null = unlimited; 0 = explicitly disabled with no quota",
    )
    reason: str | None = Field(None, max_length=500)
    expires_at: datetime | None = None


class OverrideResponse(CamelModel):
    id: UUID
    organization_id: UUID
    feature_id: UUID
    feature_key: str
    enabled: bool
    limit_value: int | None = None
    reason: str | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OverrideListResponse(CamelModel):
    overrides: list[OverrideResponse]
    total: int

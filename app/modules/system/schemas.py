"""
System module Pydantic schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.shared.base_schemas import CamelModel


# ── SystemSetting ─────────────────────────────────────────────────────────

class SystemSettingResponse(CamelModel):
    id: UUID
    key: str
    value: Any
    description: str | None
    is_public: bool
    updated_by: UUID | None
    updated_at: datetime


class SystemSettingListResponse(CamelModel):
    settings: list[SystemSettingResponse]
    count: int


class UpdateSettingRequest(CamelModel):
    value: Any = Field(..., description="New value for the setting (any JSON-serialisable type)")
    description: str | None = Field(None, description="Optional description update")
    is_public: bool | None = Field(None, description="Whether to expose setting to frontend")


# ── Health check ──────────────────────────────────────────────────────────

class HealthComponentStatus(CamelModel):
    status: str  # "ok" | "degraded" | "down"
    latency_ms: float | None = None
    detail: str | None = None


class DiskUsage(CamelModel):
    total_gb: float
    used_gb: float
    free_gb: float
    percent_used: float


class HealthResponse(CamelModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    version: str
    environment: str
    timestamp: datetime
    components: dict[str, HealthComponentStatus]
    disk: DiskUsage | None = None


# ── Admin stats ───────────────────────────────────────────────────────────

class AdminStatsResponse(CamelModel):
    total_users: int
    active_users: int
    total_organizations: int
    active_organizations: int
    total_files: int
    total_file_size_bytes: int
    active_subscriptions: int
    mrr_usd: float
    arr_usd: float
    period_new_users_30d: int
    period_new_orgs_30d: int

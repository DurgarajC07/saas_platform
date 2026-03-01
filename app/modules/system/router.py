"""
System module API router.

Endpoints
---------
GET  /system/health            – public health probe (no auth)
GET  /system/metrics           – Prometheus text format (platform admin)
GET  /system/settings          – list settings (auth required; admin sees all)
GET  /system/settings/{key}    – single setting
PUT  /system/settings/{key}    – upsert setting (platform admin)
DELETE /system/settings/{key}  – delete setting (platform admin)
GET  /admin/stats              – aggregate dashboard stats (platform admin)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.auth.dependencies import get_current_user
from app.core.middleware.metrics import metrics_response
from app.modules.auth.models import User
from app.modules.system.schemas import (
    AdminStatsResponse,
    HealthResponse,
    SystemSettingListResponse,
    SystemSettingResponse,
    UpdateSettingRequest,
)
from app.modules.system.service import SystemService
from starlette.responses import Response

router = APIRouter()


# ── Dependencies ────────────────────────────────────────────────────────────


def _require_platform_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required.",
        )
    return current_user


# ── Health ────────────────────────────────────────────────────────────────────


@router.get(
    "/system/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["System"],
)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Public health probe. Returns DB/Redis/disk status without authentication."""
    svc = SystemService(db)
    return await svc.health_check()


# ── Prometheus metrics ────────────────────────────────────────────────────────


@router.get(
    "/system/metrics",
    summary="Prometheus metrics",
    tags=["System"],
    response_class=Response,
)
async def prometheus_metrics(
    _admin: User = Depends(_require_platform_admin),
) -> Response:
    """Expose all registered Prometheus metrics in text format (platform admin only)."""
    return metrics_response()


# ── System Settings ───────────────────────────────────────────────────────────


@router.get(
    "/system/settings",
    response_model=SystemSettingListResponse,
    summary="List system settings",
    tags=["System"],
)
async def list_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SystemSettingListResponse:
    """
    • Platform admins see all settings.
    • Regular users see only public settings.
    """
    svc = SystemService(db)
    public_only = not current_user.is_platform_admin
    return await svc.list_settings(public_only=public_only)


@router.get(
    "/system/settings/{key}",
    response_model=SystemSettingResponse,
    summary="Get a single system setting",
    tags=["System"],
)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SystemSettingResponse:
    svc = SystemService(db)
    setting = await svc.get_setting(key)
    if setting is None:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found.")
    if not setting.is_public and not current_user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Access denied.")
    return setting


@router.put(
    "/system/settings/{key}",
    response_model=SystemSettingResponse,
    summary="Create or update a system setting",
    tags=["System"],
)
async def upsert_setting(
    key: str,
    payload: UpdateSettingRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_require_platform_admin),
) -> SystemSettingResponse:
    svc = SystemService(db)
    return await svc.upsert_setting(key, payload, updated_by=admin.id)


@router.delete(
    "/system/settings/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a system setting",
    tags=["System"],
)
async def delete_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_platform_admin),
) -> None:
    svc = SystemService(db)
    deleted = await svc.delete_setting(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found.")


# ── Admin stats ───────────────────────────────────────────────────────────────


@router.get(
    "/admin/stats",
    response_model=AdminStatsResponse,
    summary="Platform admin dashboard statistics",
    tags=["System"],
)
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_platform_admin),
) -> AdminStatsResponse:
    """Aggregate statistics for the platform admin dashboard."""
    svc = SystemService(db)
    return await svc.admin_stats()

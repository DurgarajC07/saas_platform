"""
Audit log endpoints.

GET  /audit/logs               — paginated list with filters (platform admin)
GET  /audit/logs/export        — CSV export (platform admin)
GET  /audit/logs/{id}          — single entry with diff view (platform admin)
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import ForbiddenException
from app.core.pagination import PaginationParams
from app.modules.audit.schemas import AuditLogDetailResponse, AuditLogListResponse
from app.modules.audit.service import AuditService
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User

router = APIRouter()


def _require_platform_admin(actor: User) -> None:
    if not actor.is_platform_admin:
        raise ForbiddenException("Platform admin access required")


# ── Dependency ───────────────────────────────────────────────────────────

def get_audit_service(session: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(session)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get(
    "/audit/logs",
    response_model=AuditLogListResponse,
    summary="List audit logs (admin)",
)
async def list_audit_logs(
    params: PaginationParams = Depends(),
    org_id: UUID | None = Query(None),
    actor_user_id: UUID | None = Query(None),
    action: str | None = Query(None, description="Substring match on action"),
    resource_type: str | None = Query(None),
    resource_id: UUID | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    actor: User = Depends(get_current_user),
    svc: AuditService = Depends(get_audit_service),
) -> AuditLogListResponse:
    _require_platform_admin(actor)
    return await svc.list_logs(
        params,
        org_id=org_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/audit/logs/export",
    summary="Export audit logs as CSV (admin)",
)
async def export_audit_logs(
    org_id: UUID | None = Query(None),
    actor_user_id: UUID | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    actor: User = Depends(get_current_user),
    svc: AuditService = Depends(get_audit_service),
) -> Response:
    _require_platform_admin(actor)
    csv_data = await svc.export_csv(
        org_id=org_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        start_date=start_date,
        end_date=end_date,
    )
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


@router.get(
    "/audit/logs/{log_id}",
    response_model=AuditLogDetailResponse,
    summary="Get single audit log entry with diff (admin)",
)
async def get_audit_log(
    log_id: UUID,
    actor: User = Depends(get_current_user),
    svc: AuditService = Depends(get_audit_service),
) -> AuditLogDetailResponse:
    _require_platform_admin(actor)
    return await svc.get_log(log_id)

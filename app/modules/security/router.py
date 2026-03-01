"""
Security endpoints.

GET    /security/login-attempts         — paginated login attempts (admin)
GET    /security/blocked-ips            — list active blocked IPs (admin)
POST   /security/blocked-ips            — manually block an IP (admin)
DELETE /security/blocked-ips/{id}       — unblock an IP (admin)
GET    /security/events                 — security event stream (admin)
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.core.pagination import PaginationParams
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.security.schemas import (
    BlockIPRequest,
    BlockedIPListResponse,
    BlockedIPResponse,
    LoginAttemptListResponse,
    SecurityEventResponse,
)
from app.modules.security.service import SecurityService

router = APIRouter()


def get_security_service(
    session: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> SecurityService:
    return SecurityService(session, redis)


@router.get(
    "/security/login-attempts",
    response_model=LoginAttemptListResponse,
    summary="List login attempts (admin)",
)
async def list_login_attempts(
    params: PaginationParams = Depends(),
    ip_address: str | None = Query(None),
    email: str | None = Query(None),
    user_id: UUID | None = Query(None),
    is_success: bool | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    actor: User = Depends(get_current_user),
    svc: SecurityService = Depends(get_security_service),
) -> LoginAttemptListResponse:
    return await svc.list_login_attempts(
        params,
        ip_address=ip_address,
        email=email,
        user_id=user_id,
        is_success=is_success,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/security/blocked-ips",
    response_model=BlockedIPListResponse,
    summary="List active blocked IPs (admin)",
)
async def list_blocked_ips(
    params: PaginationParams = Depends(),
    actor: User = Depends(get_current_user),
    svc: SecurityService = Depends(get_security_service),
) -> BlockedIPListResponse:
    return await svc.list_blocked_ips(params)


@router.post(
    "/security/blocked-ips",
    response_model=BlockedIPResponse,
    status_code=201,
    summary="Manually block an IP (admin)",
)
async def block_ip(
    data: BlockIPRequest,
    actor: User = Depends(get_current_user),
    svc: SecurityService = Depends(get_security_service),
) -> BlockedIPResponse:
    return await svc.block_ip(data, actor)


@router.delete(
    "/security/blocked-ips/{blocked_id}",
    status_code=204,
    summary="Unblock an IP (admin)",
)
async def unblock_ip(
    blocked_id: UUID,
    actor: User = Depends(get_current_user),
    svc: SecurityService = Depends(get_security_service),
) -> None:
    await svc.unblock_ip(blocked_id, actor)


@router.get(
    "/security/events",
    response_model=list[SecurityEventResponse],
    summary="Security event stream — suspicious IPs (admin)",
)
async def list_security_events(
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
    min_failures: int = Query(5, ge=1, description="Minimum failures to surface"),
    actor: User = Depends(get_current_user),
    svc: SecurityService = Depends(get_security_service),
) -> list[SecurityEventResponse]:
    return await svc.list_security_events(hours=hours, min_failures=min_failures)

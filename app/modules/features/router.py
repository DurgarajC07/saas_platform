"""
Features module router.

Route prefix (registered in main.py): /api/v1

Endpoints:
  ── Public / org-scoped ──
  GET    /features                                   List all feature definitions
  GET    /features/check                             Check multiple features for current org
                                                     Query param: ?keys=a&keys=b

  ── Platform-admin only ──
  POST   /admin/features                             Create a feature definition
  POST   /admin/plans/{plan_id}/features             Assign feature to a plan
  POST   /admin/organizations/{org_id}/feature-overrides
                                                     Grant/update org override
  DELETE /admin/organizations/{org_id}/feature-overrides/{override_id}
                                                     Remove org override
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.features.schemas import (
    AssignPlanFeatureRequest,
    CreateFeatureRequest,
    FeatureCheckResult,
    FeatureListResponse,
    FeatureResponse,
    GrantOverrideRequest,
    MultiCheckResponse,
    OverrideResponse,
    PlanFeatureResponse,
)
from app.modules.features.service import FeatureService
from app.modules.rbac.dependencies import get_current_org_id

router = APIRouter()

# ── Type aliases ──────────────────────────────────────────────────────────

CurrentUser = Annotated[User, Depends(get_current_user)]
OrgID       = Annotated[UUID, Depends(get_current_org_id)]
DB          = Annotated[AsyncSession, Depends(get_db)]
Redis       = Annotated[aioredis.Redis, Depends(get_redis)]


def _svc(db: AsyncSession, redis: aioredis.Redis) -> FeatureService:
    return FeatureService(db, redis)


# ── Feature list (public) ─────────────────────────────────────────────────

@router.get(
    "/features",
    response_model=FeatureListResponse,
    summary="List all feature definitions",
    tags=["Features"],
)
async def list_features(
    db: DB,
    redis: Redis,
) -> FeatureListResponse:
    """Returns all registered feature keys with descriptions. No auth required."""
    return await _svc(db, redis).list_features()


# ── Multi-feature check (org-scoped) ─────────────────────────────────────

@router.get(
    "/features/check",
    response_model=MultiCheckResponse,
    summary="Check multiple feature flags for the current org",
    tags=["Features"],
)
async def check_features(
    keys: Annotated[list[str], Query(min_length=1, description="Feature key(s) to check")],
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> MultiCheckResponse:
    """
    Pass one or more ``?keys=feature.key`` query parameters.
    Returns a map of ``{ "feature.key": { enabled, limit } }`` for the org.
    """
    results = await _svc(db, redis).check_many(org_id, keys)
    return MultiCheckResponse(results=results)


# ── Admin: create feature ─────────────────────────────────────────────────

@router.post(
    "/admin/features",
    response_model=FeatureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a feature definition (platform admin)",
    tags=["Features – Admin"],
)
async def create_feature(
    data: CreateFeatureRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> FeatureResponse:
    return await _svc(db, redis).create_feature(data, user, request)


# ── Admin: assign feature to plan ────────────────────────────────────────

@router.post(
    "/admin/plans/{plan_id}/features",
    response_model=PlanFeatureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a feature to a subscription plan (platform admin)",
    tags=["Features – Admin"],
)
async def assign_plan_feature(
    plan_id: UUID,
    data: AssignPlanFeatureRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> PlanFeatureResponse:
    return await _svc(db, redis).assign_plan_feature(plan_id, data, user, request)


# ── Admin: grant org feature override ────────────────────────────────────

@router.post(
    "/admin/organizations/{org_id}/feature-overrides",
    response_model=OverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant or update a feature override for an org (platform admin)",
    tags=["Features – Admin"],
)
async def grant_override(
    org_id: UUID,
    data: GrantOverrideRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> OverrideResponse:
    return await _svc(db, redis).grant_override(org_id, data, user, request)


# ── Admin: remove org feature override ───────────────────────────────────

@router.delete(
    "/admin/organizations/{org_id}/feature-overrides/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a feature override from an org (platform admin)",
    tags=["Features – Admin"],
)
async def delete_override(
    org_id: UUID,
    override_id: UUID,
    request: Request,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> None:
    await _svc(db, redis).delete_override(override_id, org_id, user, request)

"""
Feature module FastAPI dependencies.

get_feature_service   — build a FeatureService with db + redis
require_feature       — factory that returns a Depends() enforcing a feature gate

Usage in any router::

    from app.modules.features.dependencies import require_feature

    @router.post("/reports/advanced")
    async def advanced_report(
        _=require_feature("advanced_analytics"),
        user: User = Depends(get_current_user),
    ):
        ...

The ``require_feature`` dependency is completely decoupled from any specific module;
it only needs the org context (set by TenantContextMiddleware) and a FeatureService.
"""

from __future__ import annotations

from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.modules.features.service import FeatureService
from app.modules.rbac.dependencies import get_current_org_id


# ── Service factory ───────────────────────────────────────────────────────

async def get_feature_service(
    session: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> FeatureService:
    return FeatureService(session, redis)


# ── Feature-gate dependency ───────────────────────────────────────────────

def require_feature(feature_key: str) -> Depends:
    """
    Return a FastAPI ``Depends`` that raises ``ForbiddenException`` (403) when
    the current org does not have access to *feature_key*.

    Can be used anywhere a ``Depends`` is accepted:
      • As a route parameter:   ``async def handler(_=require_feature("key"))``
      • Inside Annotated[]:     ``Annotated[None, require_feature("key")]``

    No value is injected — the dependency only raises or passes through.
    """

    async def _gate(
        request: Request,
        session: AsyncSession = Depends(get_db),
        redis: aioredis.Redis = Depends(get_redis),
    ) -> None:
        org_id: UUID = await get_current_org_id(request)
        svc = FeatureService(session, redis)
        await svc.require(org_id, feature_key)

    return Depends(_gate)

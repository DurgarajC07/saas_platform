"""
RBAC module FastAPI dependencies.

get_current_org_id  — extract org UUID from request.state (set by TenantContextMiddleware)
get_rbac_service    — build an RBACService with db + redis
require             — factory that returns a Depends() enforcing a specific permission

Usage in a route::

    @router.delete("/something/{id}")
    async def delete_item(
        id: UUID,
        request: Request,
        user: Annotated[User, require("rbac.role.delete")],
        db: DB,
    ): ...

The ``require`` factory is designed to be used directly inside Annotated[]:

    AdminUser = Annotated[User, require("rbac.role.create")]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.core.exceptions import ForbiddenException
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.rbac.service import RBACService


# ── Org context ───────────────────────────────────────────────────────────

async def get_current_org_id(request: Request) -> UUID:
    """
    Extract the org UUID put on request.state by TenantContextMiddleware.
    Raises ForbiddenException (403) if no org context is present.
    """
    org_id: UUID | None = getattr(request.state, "org_id", None)
    if org_id is None:
        raise ForbiddenException(
            "Organization context required — provide X-Organization-ID or X-Org-ID header"
        )
    return org_id


# ── Service factory ───────────────────────────────────────────────────────

async def get_rbac_service(
    session: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> RBACService:
    return RBACService(session, redis)


# ── Permission-check dependency ───────────────────────────────────────────

def require(permission: str) -> Depends:
    """
    Return a FastAPI ``Depends`` that:
      1. Resolves the current user (Bearer token).
      2. Obtains the org context from request.state.
      3. Delegates to RBACService.require_permission().
      4. Returns the authenticated User on success (so routes can use it).

    Usage::

        @router.post("/roles")
        async def create_role(
            data: CreateRoleRequest,
            request: Request,
            actor: Annotated[User, require("rbac.role.create")],
            db:   DB,
        ): ...
    """

    async def _enforce(
        request: Request,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db),
        redis: aioredis.Redis = Depends(get_redis),
    ) -> User:
        org_id = await get_current_org_id(request)
        rbac = RBACService(session, redis)
        await rbac.require_permission(current_user, org_id, permission)
        return current_user

    return Depends(_enforce)


# ── Dataclass bundle ──────────────────────────────────────────────────────

@dataclass
class RBACDeps:
    """Bundle db + redis for routes that need both the service and the session."""

    session: AsyncSession
    redis: aioredis.Redis

    @property
    def rbac(self) -> RBACService:
        return RBACService(self.session, self.redis)

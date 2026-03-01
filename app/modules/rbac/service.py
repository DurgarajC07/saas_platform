"""
RBAC service — permission-checking, role management, and cache coordination.

Architecture:
  • Redis cache at ``perms:{user_id}:{org_id}`` (TTL 5 min) holds a JSON list
    of permission-name strings for each user+org combination.
  • Platform admins (User.is_platform_admin == True) bypass all permission checks.
  • System roles (is_system_role == True) cannot be mutated or deleted.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from uuid import UUID

import structlog
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.rbac.models import Role
from app.modules.rbac.repository import (
    OrganizationUserRoleRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserPermissionRepository,
)
from app.modules.rbac.schemas import (
    CreateRoleRequest,
    MemberRoleResponse,
    MemberRolesResponse,
    PermissionGroup,
    PermissionGroupedResponse,
    PermissionResponse,
    RoleListResponse,
    RolePermissionsResponse,
    RoleResponse,
    UpdateRoleRequest,
)
from app.modules.tenancy.repository import OrganizationUserRepository

logger = structlog.get_logger(__name__)

_CACHE_PREFIX = "perms"
_CACHE_TTL = 300  # 5 minutes


def _cache_key(user_id: UUID, org_id: UUID) -> str:
    return f"{_CACHE_PREFIX}:{user_id}:{org_id}"


class RBACService:
    def __init__(self, session: AsyncSession, redis: aioredis.Redis) -> None:
        self.session = session
        self.redis = redis
        self._role_repo = RoleRepository(session)
        self._perm_repo = PermissionRepository(session)
        self._role_perm_repo = RolePermissionRepository(session)
        self._org_user_role_repo = OrganizationUserRoleRepository(session)
        self._user_perm_repo = UserPermissionRepository(session)
        self._org_user_repo = OrganizationUserRepository(session)
        self._audit = AuditService(session)

    # ── Permission cache ──────────────────────────────────────────────────

    async def get_user_permissions(
        self, user_id: UUID, org_id: UUID
    ) -> set[str]:
        """
        Return the effective permission-name set for user+org.
        Result is cached in Redis for TTL seconds; miss triggers a DB query.
        """
        key = _cache_key(user_id, org_id)
        cached = await self.redis.get(key)
        if cached is not None:
            return set(json.loads(cached))

        perm_names = await self._user_perm_repo.get_user_permissions(user_id, org_id)
        await self.redis.set(key, json.dumps(perm_names), ex=_CACHE_TTL)
        return set(perm_names)

    async def has_permission(
        self, user_id: UUID, org_id: UUID, permission: str
    ) -> bool:
        """Return True if the user holds ``permission`` in the given org."""
        perms = await self.get_user_permissions(user_id, org_id)
        return permission in perms

    async def require_permission(
        self, user: User, org_id: UUID, permission: str
    ) -> None:
        """
        Raise ForbiddenException if the user does not hold ``permission``.
        Platform admins (is_platform_admin == True) always pass.
        """
        if getattr(user, "is_platform_admin", False):
            return

        if not await self.has_permission(user.id, org_id, permission):
            logger.warning(
                "rbac.permission_denied",
                user_id=str(user.id),
                org_id=str(org_id),
                permission=permission,
            )
            raise ForbiddenException(
                f"You do not have permission: {permission}"
            )

    async def invalidate_user_permissions(
        self, user_id: UUID, org_id: UUID
    ) -> None:
        """Delete the cached permission list for this user+org combination."""
        await self.redis.delete(_cache_key(user_id, org_id))
        logger.debug(
            "rbac.cache_invalidated",
            user_id=str(user_id),
            org_id=str(org_id),
        )

    # ── Role management ───────────────────────────────────────────────────

    async def list_roles(self, org_id: UUID) -> RoleListResponse:
        roles = await self._role_repo.list_by_org(org_id)
        schemas = [RoleResponse.model_validate(r) for r in roles]
        return RoleListResponse(roles=schemas, total=len(schemas))

    async def create_role(
        self,
        org_id: UUID,
        data: CreateRoleRequest,
        actor: User,
        request: Request,
    ) -> RoleResponse:
        # Guard: no duplicate name within this org
        existing = await self._role_repo.get_by_name_and_org(data.name, org_id)
        if existing:
            raise ConflictException(
                f"A role named '{data.name}' already exists in this organization"
            )

        role = await self._role_repo.create(
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            org_id=org_id,
            priority=data.priority,
        )

        await self._audit.log(
            action="rbac.role.create",
            resource_type="role",
            resource_id=role.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            new_values={"name": role.name, "priority": role.priority},
            description=f"Created role '{role.name}'",
        )

        logger.info("rbac.role.created", role_id=str(role.id), name=role.name)
        return RoleResponse.model_validate(role)

    async def update_role(
        self,
        role_id: UUID,
        org_id: UUID,
        data: UpdateRoleRequest,
        actor: User,
        request: Request,
    ) -> RoleResponse:
        role = await self._get_org_role_or_404(role_id, org_id)
        self._guard_not_system_role(role, "update")

        old = {"name": role.name, "display_name": role.display_name, "priority": role.priority}

        # Name change — check uniqueness
        if data.name and data.name != role.name:
            conflict = await self._role_repo.get_by_name_and_org(data.name, org_id)
            if conflict and conflict.id != role_id:
                raise ConflictException(
                    f"A role named '{data.name}' already exists in this organization"
                )

        role = await self._role_repo.update(
            role,
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            priority=data.priority,
        )

        await self._audit.log(
            action="rbac.role.update",
            resource_type="role",
            resource_id=role.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            old_values=old,
            new_values={"name": role.name, "display_name": role.display_name, "priority": role.priority},
            description=f"Updated role '{role.name}'",
        )

        return RoleResponse.model_validate(role)

    async def delete_role(
        self,
        role_id: UUID,
        org_id: UUID,
        actor: User,
        request: Request,
    ) -> None:
        role = await self._get_org_role_or_404(role_id, org_id)
        self._guard_not_system_role(role, "delete")

        await self._audit.log(
            action="rbac.role.delete",
            resource_type="role",
            resource_id=role.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            old_values={"name": role.name},
            description=f"Deleted role '{role.name}'",
        )

        await self._role_repo.delete(role)
        logger.info("rbac.role.deleted", role_id=str(role_id))

    # ── Role-permission management ────────────────────────────────────────

    async def list_role_permissions(
        self,
        role_id: UUID,
        org_id: UUID,
    ) -> RolePermissionsResponse:
        role = await self._get_org_role_or_404(role_id, org_id)
        perms = await self._perm_repo.list_by_role(role.id)
        return RolePermissionsResponse(
            role_id=role.id,
            permissions=[PermissionResponse.model_validate(p) for p in perms],
        )

    async def set_role_permissions(
        self,
        role_id: UUID,
        org_id: UUID,
        permission_ids: list[UUID],
        actor: User,
        request: Request,
    ) -> RolePermissionsResponse:
        role = await self._get_org_role_or_404(role_id, org_id)
        self._guard_not_system_role(role, "modify permissions of")

        # Validate all permission IDs exist
        perms = await self._perm_repo.get_by_ids(permission_ids)
        found_ids = {p.id for p in perms}
        missing = set(permission_ids) - found_ids
        if missing:
            raise BadRequestException(
                f"Unknown permission IDs: {', '.join(str(x) for x in missing)}"
            )

        await self._role_perm_repo.set_permissions(role.id, permission_ids)

        await self._audit.log(
            action="rbac.role_permission.set",
            resource_type="role",
            resource_id=role.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            new_values={"permission_count": len(permission_ids)},
            description=f"Set {len(permission_ids)} permission(s) on role '{role.name}'",
        )

        # Invalidate cache for all members of this org that hold this role
        # (pragmatic approach: invalidate org-wide on role permission changes)
        await self._invalidate_org_role_caches(org_id, role.id)

        return RolePermissionsResponse(
            role_id=role.id,
            permissions=[PermissionResponse.model_validate(p) for p in perms],
        )

    async def list_all_permissions(self) -> PermissionGroupedResponse:
        perms = await self._perm_repo.list_all()
        # Group by module
        groups: dict[str, list[PermissionResponse]] = {}
        for p in perms:
            groups.setdefault(p.module, []).append(PermissionResponse.model_validate(p))
        group_list = [
            PermissionGroup(module=mod, permissions=grouped)
            for mod, grouped in sorted(groups.items())
        ]
        return PermissionGroupedResponse(groups=group_list, total=len(perms))

    # ── Member role management ────────────────────────────────────────────

    async def get_member_roles(
        self,
        org_member_id: UUID,
        org_id: UUID,
    ) -> MemberRolesResponse:
        await self._get_org_member_or_404(org_member_id, org_id)
        assignments = await self._org_user_role_repo.list_by_org_user(org_member_id)
        role_responses = [
            MemberRoleResponse(
                organization_user_id=asgn.organization_user_id,
                role=RoleResponse.model_validate(asgn.role),
                assigned_at=asgn.assigned_at,
                assigned_by=asgn.assigned_by,
            )
            for asgn in assignments
        ]
        return MemberRolesResponse(
            organization_user_id=org_member_id,
            roles=role_responses,
        )

    async def assign_member_role(
        self,
        org_member_id: UUID,
        role_id: UUID,
        org_id: UUID,
        actor: User,
        request: Request,
    ) -> MemberRolesResponse:
        await self._get_org_member_or_404(org_member_id, org_id)
        role = await self._get_org_role_or_404(role_id, org_id)

        # Guard: don't assign if already holds this role
        existing = await self._org_user_role_repo.get(org_member_id, role_id)
        if existing:
            raise ConflictException("Member already has this role assigned")

        await self._org_user_role_repo.assign(
            org_member_id, role.id, assigned_by=actor.id
        )

        # Determine user_id for cache invalidation
        org_member = await self._org_user_repo.get_by_id(org_member_id)
        await self.invalidate_user_permissions(org_member.user_id, org_id)

        await self._audit.log(
            action="rbac.user_role.assign",
            resource_type="organization_user_role",
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            new_values={
                "org_member_id": str(org_member_id),
                "role_id": str(role_id),
                "role_name": role.name,
            },
            description=f"Assigned role '{role.name}' to member",
        )

        return await self.get_member_roles(org_member_id, org_id)

    async def revoke_member_role(
        self,
        org_member_id: UUID,
        role_id: UUID,
        org_id: UUID,
        actor: User,
        request: Request,
    ) -> None:
        await self._get_org_member_or_404(org_member_id, org_id)
        role = await self._get_org_role_or_404(role_id, org_id)

        existing = await self._org_user_role_repo.get(org_member_id, role_id)
        if not existing:
            raise NotFoundException("Member does not have this role assigned")

        await self._org_user_role_repo.revoke(org_member_id, role_id)

        # Invalidate cache
        org_member = await self._org_user_repo.get_by_id(org_member_id)
        await self.invalidate_user_permissions(org_member.user_id, org_id)

        await self._audit.log(
            action="rbac.user_role.revoke",
            resource_type="organization_user_role",
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            old_values={
                "org_member_id": str(org_member_id),
                "role_id": str(role_id),
                "role_name": role.name,
            },
            description=f"Revoked role '{role.name}' from member",
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _get_org_role_or_404(self, role_id: UUID, org_id: UUID) -> Role:
        """
        Fetch a role and assert it belongs to the org OR is a system role
        (system roles are accessible from any org context).
        """
        role = await self._role_repo.get_by_id(role_id)
        if not role:
            raise NotFoundException("Role not found")
        if not role.is_system_role and role.organization_id != org_id:
            raise NotFoundException("Role not found in this organization")
        return role

    @staticmethod
    def _guard_not_system_role(role: Role, action: str) -> None:
        if role.is_system_role:
            raise ForbiddenException(
                f"Cannot {action} a system role"
            )

    async def _get_org_member_or_404(
        self, org_member_id: UUID, org_id: UUID
    ) -> object:
        member = await self._org_user_repo.get_by_id(org_member_id)
        if not member or member.organization_id != org_id:
            raise NotFoundException("Organization member not found")
        return member

    async def _invalidate_org_role_caches(
        self, org_id: UUID, role_id: UUID
    ) -> None:
        """
        Invalidate permission caches for all org members that hold role_id.
        Uses a Redis SCAN so we don't load the full org member list from DB.
        """
        pattern = f"{_CACHE_PREFIX}:*:{org_id}"
        async for key in self.redis.scan_iter(match=pattern):
            await self.redis.delete(key)

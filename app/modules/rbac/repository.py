"""
RBAC module repositories.

RoleRepository                  — Role CRUD (system + org-scoped)
PermissionRepository            — read-only permission catalogue
RolePermissionRepository        — manage permissions assigned to a role
OrganizationUserRoleRepository  — assign/revoke/list roles for org members
UserPermissionRepository        — efficient flat-permission look-up per user+org
"""

from __future__ import annotations

from datetime import datetime, UTC
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.rbac.models import (
    OrganizationUserRole,
    Permission,
    Role,
    RolePermission,
)


# ── RoleRepository ────────────────────────────────────────────────────────

class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_org(self, org_id: UUID) -> list[Role]:
        """Return all roles visible to an org: system-wide + org-specific."""
        result = await self.session.execute(
            select(Role).where(
                (Role.organization_id == org_id) | Role.is_system_role.is_(True)
            ).order_by(Role.priority.desc(), Role.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, role_id: UUID) -> Role | None:
        result = await self.session.execute(
            select(Role).where(Role.id == role_id)
        )
        return result.scalar_one_or_none()

    async def get_system_role_by_name(self, name: str) -> Role | None:
        """Return the system-level Role with the given name, or None."""
        result = await self.session.execute(
            select(Role).where(
                Role.is_system_role.is_(True),
                Role.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name_and_org(self, name: str, org_id: UUID) -> Role | None:
        result = await self.session.execute(
            select(Role).where(
                Role.name == name,
                Role.organization_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        display_name: str | None = None,
        description: str | None = None,
        org_id: UUID,
        priority: int = 0,
    ) -> Role:
        now = datetime.now(UTC)
        role = Role(
            name=name,
            display_name=display_name,
            description=description,
            organization_id=org_id,
            is_system_role=False,
            is_default=False,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        self.session.add(role)
        await self.session.flush()
        return role

    async def update(
        self,
        role: Role,
        *,
        name: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        priority: int | None = None,
    ) -> Role:
        if name is not None:
            role.name = name
        if display_name is not None:
            role.display_name = display_name
        if description is not None:
            role.description = description
        if priority is not None:
            role.priority = priority
        role.updated_at = datetime.now(UTC)
        await self.session.flush()
        return role

    async def delete(self, role: Role) -> None:
        await self.session.delete(role)
        await self.session.flush()


# ── PermissionRepository ──────────────────────────────────────────────────

class PermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[Permission]:
        result = await self.session.execute(
            select(Permission).order_by(Permission.module, Permission.resource, Permission.action)
        )
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> Permission | None:
        result = await self.session.execute(
            select(Permission).where(Permission.name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, ids: list[UUID]) -> list[Permission]:
        if not ids:
            return []
        result = await self.session.execute(
            select(Permission).where(Permission.id.in_(ids))
        )
        return list(result.scalars().all())

    async def list_by_role(self, role_id: UUID) -> list[Permission]:
        """Return all permissions assigned to the given role."""
        result = await self.session.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.module, Permission.resource, Permission.action)
        )
        return list(result.scalars().all())


# ── RolePermissionRepository ──────────────────────────────────────────────

class RolePermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_permissions(
        self,
        role_id: UUID,
        permission_ids: list[UUID],
        granted_by: UUID | None = None,
    ) -> None:
        """Atomically replace all permissions for a role (bulk PUT semantics)."""
        # Delete existing
        await self.session.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        # Insert new set
        now = datetime.now(UTC)
        for perm_id in permission_ids:
            self.session.add(
                RolePermission(
                    role_id=role_id,
                    permission_id=perm_id,
                    conditions={},
                    granted_at=now,
                )
            )
        await self.session.flush()

    async def get_by_role(self, role_id: UUID) -> list[RolePermission]:
        result = await self.session.execute(
            select(RolePermission).where(RolePermission.role_id == role_id)
        )
        return list(result.scalars().all())


# ── OrganizationUserRoleRepository ────────────────────────────────────────

class OrganizationUserRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def assign(
        self,
        org_user_id: UUID,
        role_id: UUID,
        assigned_by: UUID | None = None,
    ) -> OrganizationUserRole:
        """Assign a role to an organization-user membership row."""
        record = OrganizationUserRole(
            organization_user_id=org_user_id,
            role_id=role_id,
            assigned_at=datetime.now(UTC),
            assigned_by=assigned_by,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def revoke(self, org_user_id: UUID, role_id: UUID) -> None:
        """Remove a role assignment."""
        await self.session.execute(
            delete(OrganizationUserRole).where(
                OrganizationUserRole.organization_user_id == org_user_id,
                OrganizationUserRole.role_id == role_id,
            )
        )

    async def list_by_org_user(
        self, org_user_id: UUID
    ) -> list[OrganizationUserRole]:
        """List all role assignments for a single membership record."""
        result = await self.session.execute(
            select(OrganizationUserRole)
            .where(OrganizationUserRole.organization_user_id == org_user_id)
            .options(selectinload(OrganizationUserRole.role))
        )
        return list(result.scalars().all())

    async def get(
        self, org_user_id: UUID, role_id: UUID
    ) -> OrganizationUserRole | None:
        result = await self.session.execute(
            select(OrganizationUserRole).where(
                OrganizationUserRole.organization_user_id == org_user_id,
                OrganizationUserRole.role_id == role_id,
            )
        )
        return result.scalar_one_or_none()


# ── UserPermissionRepository ──────────────────────────────────────────────

class UserPermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_permissions(
        self, user_id: UUID, org_id: UUID
    ) -> list[str]:
        """
        Return the flat list of permission *names* for a user within an org.

        Join path:
          users → organization_users (filtered by org_id+user_id)
                → organization_user_roles
                → roles → role_permissions → permissions
        """
        from app.modules.tenancy.models import OrganizationUser

        result = await self.session.execute(
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(
                OrganizationUserRole,
                OrganizationUserRole.role_id == Role.id,
            )
            .join(
                OrganizationUser,
                OrganizationUser.id == OrganizationUserRole.organization_user_id,
            )
            .where(
                OrganizationUser.user_id == user_id,
                OrganizationUser.organization_id == org_id,
            )
            .distinct()
        )
        return list(result.scalars().all())

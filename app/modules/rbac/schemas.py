"""
RBAC module Pydantic schemas.

RoleResponse               — single role representation
CreateRoleRequest          — body for POST /roles
UpdateRoleRequest          — body for PATCH /roles/{id}
RoleListResponse           — list wrapper
PermissionResponse         — single permission representation
PermissionGroup            — permissions grouped by module (for GET /permissions)
RolePermissionsRequest     — body for PUT /roles/{id}/permissions
MemberRoleResponse         — single member-role-assignment representation
MemberRolesResponse        — list of role assignments for one member
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.shared.base_schemas import CamelModel


# ── Role schemas ──────────────────────────────────────────────────────────

class RoleResponse(CamelModel):
    id: UUID
    name: str
    display_name: str | None = None
    description: str | None = None
    organization_id: UUID | None = None
    is_system_role: bool
    is_default: bool
    priority: int
    created_at: datetime
    updated_at: datetime


class CreateRoleRequest(CamelModel):
    name: str = Field(..., min_length=2, max_length=100)
    display_name: str | None = Field(None, max_length=150)
    description: str | None = Field(None, max_length=500)
    priority: int = Field(0, ge=0, le=100)


class UpdateRoleRequest(CamelModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    display_name: str | None = Field(None, max_length=150)
    description: str | None = Field(None, max_length=500)
    priority: int | None = Field(None, ge=0, le=100)


class RoleListResponse(CamelModel):
    roles: list[RoleResponse]
    total: int


# ── Permission schemas ────────────────────────────────────────────────────

class PermissionResponse(CamelModel):
    id: UUID
    name: str
    display_name: str | None = None
    description: str | None = None
    module: str
    resource: str
    action: str
    created_at: datetime
    updated_at: datetime


class PermissionGroup(CamelModel):
    """All permissions for one module, grouped for the UI."""
    module: str
    permissions: list[PermissionResponse]


class PermissionGroupedResponse(CamelModel):
    groups: list[PermissionGroup]
    total: int


class RolePermissionsRequest(CamelModel):
    """Body for PUT /roles/{id}/permissions — replaces the full set."""
    permission_ids: list[UUID] = Field(default_factory=list)


class RolePermissionsResponse(CamelModel):
    role_id: UUID
    permissions: list[PermissionResponse]


# ── Member-role assignment schemas ────────────────────────────────────────

class MemberRoleResponse(CamelModel):
    organization_user_id: UUID
    role: RoleResponse
    assigned_at: datetime
    assigned_by: UUID | None = None


class MemberRolesResponse(CamelModel):
    organization_user_id: UUID
    roles: list[MemberRoleResponse]

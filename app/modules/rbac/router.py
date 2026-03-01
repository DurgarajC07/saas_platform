"""
RBAC module router.

All endpoints are protected by Bearer-token auth.
Most mutating endpoints also require a specific RBAC permission via the
``require()`` dependency factory.

Route prefix (registered in main.py): /api/v1/rbac

Endpoints:
  GET    /roles                              — list roles for the current org
  POST   /roles                              — create a custom org role
  PATCH  /roles/{role_id}                   — update a custom org role
  DELETE /roles/{role_id}                   — delete a custom org role
  GET    /roles/{role_id}/permissions       — list all permissions on a role
  PUT    /roles/{role_id}/permissions       — bulk-replace role permissions
  GET    /permissions                       — list all permissions (grouped by module)
  GET    /members/{member_id}/roles         — list roles assigned to an org member
  PUT    /members/{member_id}/roles/{role_id}    — assign role to member
  DELETE /members/{member_id}/roles/{role_id}    — revoke role from member
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.rbac.dependencies import get_current_org_id, get_rbac_service, require
from app.modules.rbac.schemas import (
    CreateRoleRequest,
    MemberRolesResponse,
    PermissionGroupedResponse,
    RoleListResponse,
    RolePermissionsRequest,
    RolePermissionsResponse,
    RoleResponse,
    UpdateRoleRequest,
)
from app.modules.rbac.service import RBACService
from app.shared.base_schemas import CamelModel

router = APIRouter()

# ── Convenience aliases ───────────────────────────────────────────────────
CurrentUser = Annotated[User, Depends(get_current_user)]
OrgID       = Annotated[UUID, Depends(get_current_org_id)]
RBAC        = Annotated[RBACService, Depends(get_rbac_service)]


class MessageResponse(CamelModel):
    message: str = "Success"


# ═══════════════════════════════════════════════════════════════════════════
# Roles — CRUD
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/roles",
    response_model=RoleListResponse,
    summary="List roles for the current organization",
)
async def list_roles(
    user: CurrentUser,
    org_id: OrgID,
    rbac: RBAC,
) -> RoleListResponse:
    """
    Return all roles visible to this org — both system-wide roles
    (owner, admin, member, viewer) and any custom org roles.
    Requires: ``rbac.role.list`` permission.
    """
    await rbac.require_permission(user, org_id, "rbac.role.list")
    return await rbac.list_roles(org_id)


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role in the current organization",
)
async def create_role(
    data: CreateRoleRequest,
    request: Request,
    user: Annotated[User, require("rbac.role.create")],
    org_id: OrgID,
    rbac: RBAC,
) -> RoleResponse:
    return await rbac.create_role(org_id, data, user, request)


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    summary="Update a custom role",
)
async def update_role(
    role_id: UUID,
    data: UpdateRoleRequest,
    request: Request,
    user: Annotated[User, require("rbac.role.update")],
    org_id: OrgID,
    rbac: RBAC,
) -> RoleResponse:
    return await rbac.update_role(role_id, org_id, data, user, request)


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom role",
)
async def delete_role(
    role_id: UUID,
    request: Request,
    user: Annotated[User, require("rbac.role.delete")],
    org_id: OrgID,
    rbac: RBAC,
) -> None:
    await rbac.delete_role(role_id, org_id, user, request)


# ═══════════════════════════════════════════════════════════════════════════
# Role Permissions
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/roles/{role_id}/permissions",
    response_model=RolePermissionsResponse,
    summary="List permissions assigned to a role",
)
async def list_role_permissions(
    role_id: UUID,
    user: CurrentUser,
    org_id: OrgID,
    rbac: RBAC,
) -> RolePermissionsResponse:
    await rbac.require_permission(user, org_id, "rbac.permission.list")
    return await rbac.list_role_permissions(role_id, org_id)


@router.put(
    "/roles/{role_id}/permissions",
    response_model=RolePermissionsResponse,
    summary="Replace all permissions for a role (bulk PUT)",
)
async def set_role_permissions(
    role_id: UUID,
    data: RolePermissionsRequest,
    request: Request,
    user: Annotated[User, require("rbac.role_permission.grant")],
    org_id: OrgID,
    rbac: RBAC,
) -> RolePermissionsResponse:
    return await rbac.set_role_permissions(
        role_id, org_id, data.permission_ids, user, request
    )


# ═══════════════════════════════════════════════════════════════════════════
# Permissions catalogue
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/permissions",
    response_model=PermissionGroupedResponse,
    summary="List all permissions grouped by module",
)
async def list_all_permissions(
    user: CurrentUser,
    org_id: OrgID,
    rbac: RBAC,
) -> PermissionGroupedResponse:
    await rbac.require_permission(user, org_id, "rbac.permission.list")
    return await rbac.list_all_permissions()


# ═══════════════════════════════════════════════════════════════════════════
# Member role assignments
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/members/{member_id}/roles",
    response_model=MemberRolesResponse,
    summary="List roles assigned to an organization member",
)
async def get_member_roles(
    member_id: UUID,
    user: CurrentUser,
    org_id: OrgID,
    rbac: RBAC,
) -> MemberRolesResponse:
    await rbac.require_permission(user, org_id, "rbac.user_role.list")
    return await rbac.get_member_roles(member_id, org_id)


@router.put(
    "/members/{member_id}/roles/{role_id}",
    response_model=MemberRolesResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign a role to an organization member",
)
async def assign_member_role(
    member_id: UUID,
    role_id: UUID,
    request: Request,
    user: Annotated[User, require("rbac.user_role.assign")],
    org_id: OrgID,
    rbac: RBAC,
) -> MemberRolesResponse:
    return await rbac.assign_member_role(member_id, role_id, org_id, user, request)


@router.delete(
    "/members/{member_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a role from an organization member",
)
async def revoke_member_role(
    member_id: UUID,
    role_id: UUID,
    request: Request,
    user: Annotated[User, require("rbac.user_role.revoke")],
    org_id: OrgID,
    rbac: RBAC,
) -> None:
    await rbac.revoke_member_role(member_id, role_id, org_id, user, request)

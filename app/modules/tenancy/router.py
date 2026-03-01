"""
Tenancy module router — organization management, member management,
invitation workflow, and domain verification.

All endpoints require authentication except POST /invitations/accept
which requires the token in the request body (but the accepting user
must be logged in to associate the invitation with their account).

Route prefix (registered in main.py): /api/v1
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.pagination import PaginationParams
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.tenancy.schemas import (
    AcceptInvitationRequest,
    AddDomainRequest,
    CreateOrgRequest,
    DomainResponse,
    InvitationResponse,
    InviteRequest,
    MemberListResponse,
    MemberResponse,
    OrgResponse,
    UpdateMemberRoleRequest,
    UpdateOrgRequest,
)
from app.modules.tenancy.service import TenancyService
from app.shared.base_schemas import CamelModel

router = APIRouter()

# ── Convenience type aliases ──────────────────────────────────────────────
CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]


class MessageResponse(CamelModel):
    message: str = "Success"


# ═══════════════════════════════════════════════════════════════════════════
# Organizations
# ═══════════════════════════════════════════════════════════════════════════

@router.post(
    "/organizations",
    response_model=OrgResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new organization",
)
async def create_organization(
    data: CreateOrgRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> OrgResponse:
    """
    Create a new organization.  The authenticated user becomes the owner
    and is automatically added as an active member.
    """
    svc = TenancyService(db)
    return await svc.create_organization(data, user, request)


@router.get(
    "/organizations/{slug}",
    response_model=OrgResponse,
    summary="Get organization by slug",
)
async def get_organization_by_slug(
    slug: str,
    user: CurrentUser,
    db: DB,
) -> OrgResponse:
    """
    Retrieve public organization details by its URL slug.
    The caller must be a member of the organization.
    """
    svc = TenancyService(db)
    return await svc.get_organization_by_slug(slug, user)


@router.patch(
    "/organizations/{org_id}",
    response_model=OrgResponse,
    summary="Update organization settings",
)
async def update_organization(
    org_id: UUID,
    data: UpdateOrgRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> OrgResponse:
    """Update organization name, branding, locale, or timezone.  Requires 'admin' role."""
    svc = TenancyService(db)
    return await svc.update_organization(org_id, data, user, request)


@router.delete(
    "/organizations/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an organization",
)
async def delete_organization(
    org_id: UUID,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> None:
    """Soft-delete an organization (sets deleted_at).  Requires 'owner' role."""
    svc = TenancyService(db)
    await svc.delete_organization(org_id, user, request)


# ═══════════════════════════════════════════════════════════════════════════
# Members
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/organizations/{org_id}/members",
    response_model=MemberListResponse,
    summary="List organization members",
)
async def list_members(
    org_id: UUID,
    user: CurrentUser,
    db: DB,
    params: Annotated[PaginationParams, Depends()],
) -> MemberListResponse:
    """Return a paginated list of organization members with their profiles."""
    svc = TenancyService(db)
    return await svc.list_members(org_id, user, params)


@router.delete(
    "/organizations/{org_id}/members/{uid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from the organization",
)
async def remove_member(
    org_id: UUID,
    uid: UUID,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> None:
    """
    Remove a member (sets status='deactivated').
    Requires 'admin' role.  Only owners can remove other owners.
    """
    svc = TenancyService(db)
    await svc.remove_member(org_id, uid, user, request)


@router.patch(
    "/organizations/{org_id}/members/{uid}/role",
    response_model=MemberResponse,
    summary="Change a member's organization role",
)
async def update_member_role(
    org_id: UUID,
    uid: UUID,
    data: UpdateMemberRoleRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> MemberResponse:
    """
    Change the org_role of an existing member.
    Requires 'admin' role.  Only owners can assign the 'owner' role.
    """
    svc = TenancyService(db)
    return await svc.update_member_role(org_id, uid, data, user, request)


# ═══════════════════════════════════════════════════════════════════════════
# Invitations
# ═══════════════════════════════════════════════════════════════════════════

@router.post(
    "/organizations/{org_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user to the organization",
)
async def invite_member(
    org_id: UUID,
    data: InviteRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> InvitationResponse:
    """
    Create and send an invitation email.
    Requires 'admin' role.  Seat-limit is enforced.
    """
    svc = TenancyService(db)
    return await svc.invite_member(org_id, data, user, request)


@router.get(
    "/organizations/{org_id}/invitations",
    response_model=list[InvitationResponse],
    summary="List pending invitations",
)
async def list_invitations(
    org_id: UUID,
    user: CurrentUser,
    db: DB,
    params: Annotated[PaginationParams, Depends()],
) -> list[InvitationResponse]:
    """Return all pending invitations for the organization.  Requires 'admin' role."""
    svc = TenancyService(db)
    return await svc.list_invitations(org_id, user, params)


@router.delete(
    "/organizations/{org_id}/invitations/{invitation_id}",
    response_model=MessageResponse,
    summary="Revoke a pending invitation",
)
async def revoke_invitation(
    org_id: UUID,
    invitation_id: UUID,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """Revoke a pending invitation.  Requires 'admin' role."""
    svc = TenancyService(db)
    await svc.revoke_invitation(org_id, invitation_id, user, request)
    return MessageResponse(message="Invitation revoked")


@router.post(
    "/invitations/accept",
    response_model=OrgResponse,
    summary="Accept an invitation",
)
async def accept_invitation(
    data: AcceptInvitationRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> OrgResponse:
    """
    Accept an invitation by providing the token from the invitation email.
    The authenticated user's email must match the invitation's email address.
    Returns the joined Organization on success.
    """
    svc = TenancyService(db)
    return await svc.accept_invitation(data, user, request)


# ═══════════════════════════════════════════════════════════════════════════
# Domains
# ═══════════════════════════════════════════════════════════════════════════

@router.post(
    "/organizations/{org_id}/domains",
    response_model=DomainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a domain for verification",
)
async def add_domain(
    org_id: UUID,
    data: AddDomainRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> DomainResponse:
    """
    Register a domain for TXT-record verification.
    Returns the domain record with ``verificationToken`` to add as a DNS TXT record
    at ``_saas-verify.<domain>``.  Requires 'admin' role.
    """
    svc = TenancyService(db)
    return await svc.add_domain(org_id, data, user, request)


@router.get(
    "/organizations/{org_id}/domains",
    response_model=list[DomainResponse],
    summary="List organization domains",
)
async def list_domains(
    org_id: UUID,
    user: CurrentUser,
    db: DB,
) -> list[DomainResponse]:
    """List all domains registered for the organization."""
    svc = TenancyService(db)
    return await svc.list_domains(org_id, user)


@router.delete(
    "/organizations/{org_id}/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a domain",
)
async def delete_domain(
    org_id: UUID,
    domain_id: UUID,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> None:
    """Remove a domain from the organization.  Requires 'admin' role."""
    svc = TenancyService(db)
    await svc.delete_domain(org_id, domain_id, user, request)


@router.post(
    "/organizations/{org_id}/domains/{domain_id}/verify",
    response_model=DomainResponse,
    summary="Trigger DNS TXT record verification",
)
async def verify_domain(
    org_id: UUID,
    domain_id: UUID,
    request: Request,
    user: CurrentUser,
    db: DB,
) -> DomainResponse:
    """
    Attempt to verify domain ownership by resolving DNS TXT records.
    Looks for ``_saas-verify.<domain>`` TXT record matching the stored token.
    Returns the verified domain on success.  Requires 'admin' role.
    """
    svc = TenancyService(db)
    return await svc.verify_domain(org_id, domain_id, user, request)

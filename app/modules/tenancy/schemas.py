"""
Tenancy module Pydantic schemas.

Covers: Organization CRUD, member management, invitations, domain verification.
All models inherit CamelModel — snake_case Python, camelCase JSON/OpenAPI.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.shared.base_schemas import CamelModel, PaginatedResponse


# ── Organization ──────────────────────────────────────────────────────────

class CreateOrgRequest(CamelModel):
    name: str = Field(min_length=2, max_length=255)
    timezone: str = Field(default="UTC", max_length=100)
    locale: str = Field(default="en", max_length=20)
    currency: str = Field(default="USD", max_length=10)
    website: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=150)


class UpdateOrgRequest(CamelModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    timezone: str | None = Field(default=None, max_length=100)
    locale: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, max_length=10)
    website: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=150)
    logo_url: str | None = None


class OrgResponse(CamelModel):
    id: UUID
    name: str
    slug: str
    logo_url: str | None = None
    website: str | None = None
    industry: str | None = None
    owner_user_id: UUID | None = None
    timezone: str
    locale: str
    currency: str
    max_seats: int | None = None
    is_active: bool
    onboarding_completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── Members ───────────────────────────────────────────────────────────────

class UserBrief(CamelModel):
    """Minimal User projection embedded in member responses."""
    id: UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


class MemberResponse(CamelModel):
    """OrganizationUser with nested user details."""
    id: UUID
    organization_id: UUID
    user: UserBrief
    org_role: str
    status: str
    joined_at: datetime
    created_at: datetime
    suspended_at: datetime | None = None
    suspension_reason: str | None = None


class MemberListResponse(CamelModel):
    members: list[MemberResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class UpdateMemberRoleRequest(CamelModel):
    org_role: str = Field(pattern="^(owner|admin|member|viewer)$")


class SuspendMemberRequest(CamelModel):
    reason: str | None = Field(default=None, max_length=500)


# ── Invitations ───────────────────────────────────────────────────────────

class InviteRequest(CamelModel):
    email: EmailStr
    org_role: str = Field(default="member", pattern="^(admin|member|viewer)$")


class InvitationResponse(CamelModel):
    id: UUID
    organization_id: UUID
    email: str
    org_role: str
    status: str
    invited_by: UUID
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime
    token: str  # returned so the inviter/UI can share the accept link


class AcceptInvitationRequest(CamelModel):
    token: str = Field(min_length=10)


# ── Domains ───────────────────────────────────────────────────────────────

class AddDomainRequest(CamelModel):
    domain: str = Field(min_length=3, max_length=255)

    @field_validator("domain")
    @classmethod
    def normalise_domain(cls, v: str) -> str:
        """Strip scheme, trailing slash, and leading 'www.' for consistency."""
        domain = v.lower().strip()
        for prefix in ("https://", "http://"):
            if domain.startswith(prefix):
                domain = domain[len(prefix):]
        domain = domain.rstrip("/")
        # Strip leading www.
        if domain.startswith("www."):
            domain = domain[4:]
        return domain


class DomainResponse(CamelModel):
    id: UUID
    organization_id: UUID
    domain: str
    is_verified: bool
    verification_token: str | None = None
    verified_at: datetime | None = None
    created_at: datetime


# ── Convenience re-exports ─────────────────────────────────────────────────

# Typed paginated responses
OrgListResponse = PaginatedResponse[OrgResponse]

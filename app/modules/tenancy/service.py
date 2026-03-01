"""
Tenancy service — business logic for multi-tenant organization management.

Responsibilities:
  • Organization CRUD with unique-slug generation
  • Member management (list / remove / suspend / change-role)
  • Invitation workflow (invite / list / accept / revoke)
  • Domain verification (add / list / verify TXT / delete)
  • Seat-limit enforcement (via Organization.max_seats or active subscription)
  • Audit log entry creation for every mutating operation
"""

from __future__ import annotations

import math
import secrets
from datetime import datetime, timedelta, UTC
from uuid import UUID

import dns.asyncresolver
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.utils.slug import make_slug
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.billing.repository import SubscriptionRepository
from app.modules.rbac.repository import (
    OrganizationUserRoleRepository,
    RoleRepository,
)
from app.modules.tenancy.models import (
    Invitation,
    Organization,
    OrganizationDomain,
    OrganizationUser,
)
from app.modules.tenancy.repository import (
    InvitationRepository,
    OrganizationDomainRepository,
    OrganizationRepository,
    OrganizationUserRepository,
)
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
    UserBrief,
)
from app.core.pagination import PaginationParams, paginate

logger = structlog.get_logger(__name__)

# ── Role hierarchy ─────────────────────────────────────────────────────────
_ROLE_RANK: dict[str, int] = {"owner": 4, "admin": 3, "member": 2, "viewer": 1}

# DNS TXT record prefix for domain verification
_DNS_TXT_PREFIX = "_saas-verify"

# Invitation expiry
_INVITE_TTL_DAYS = 7


# ── TenancyService ────────────────────────────────────────────────────────

class TenancyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.org_repo = OrganizationRepository(session)
        self.org_user_repo = OrganizationUserRepository(session)
        self.invitation_repo = InvitationRepository(session)
        self.domain_repo = OrganizationDomainRepository(session)
        self.role_repo = RoleRepository(session)
        self.org_user_role_repo = OrganizationUserRoleRepository(session)
        self.subscription_repo = SubscriptionRepository(session)
        self.audit = AuditService(session)

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _generate_unique_slug(self, name: str) -> str:
        """Derive a URL-safe slug that doesn't collide with existing rows."""
        base = make_slug(name, max_length=50)
        candidate = base
        counter = 1
        while await self.org_repo.slug_exists(candidate):
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    async def _get_member(
        self, org_id: UUID, user_id: UUID
    ) -> OrganizationUser:
        """Return the OrganizationUser row, raising 403 if not found."""
        ou = await self.org_user_repo.get_by_org_and_user(org_id, user_id)
        if not ou or ou.status not in ("active", "invited"):
            raise ForbiddenException("You are not a member of this organization")
        return ou

    def _require_role(
        self, org_user: OrganizationUser, min_role: str
    ) -> None:
        """Raise ForbiddenException if org_user's role is below min_role."""
        if _ROLE_RANK.get(org_user.org_role, 0) < _ROLE_RANK[min_role]:
            raise ForbiddenException(
                f"Required organization role: {min_role} (you have: {org_user.org_role})"
            )

    async def _get_org_or_404(self, org_id: UUID) -> Organization:
        org = await self.org_repo.get_by_id(org_id)
        if not org:
            raise NotFoundException("Organization not found")
        return org

    async def _check_seat_limit(self, org: Organization) -> None:
        """Raise ForbiddenException when the seat limit for the org is reached."""
        # Prefer plan-level limit via active subscription
        sub = await self.subscription_repo.get_active_by_org(org.id)
        max_seats: int | None = None

        if sub and sub.plan.max_seats is not None:
            max_seats = sub.plan.max_seats
        elif org.max_seats is not None:
            max_seats = org.max_seats

        if max_seats is not None:
            active_count = await self.org_user_repo.count_active(org.id)
            if active_count >= max_seats:
                raise ForbiddenException(
                    f"Seat limit reached ({active_count}/{max_seats}) for current plan"
                )

    # ── Organization CRUD ─────────────────────────────────────────────────

    async def create_organization(
        self, data: CreateOrgRequest, owner: User, request: Request
    ) -> OrgResponse:
        slug = await self._generate_unique_slug(data.name)

        org = await self.org_repo.create(
            name=data.name,
            slug=slug,
            owner_user_id=owner.id,
            timezone=data.timezone,
            locale=data.locale,
            currency=data.currency,
            website=data.website,
            industry=data.industry,
            is_active=True,
        )

        # Add owner as active member
        org_user = await self.org_user_repo.create(
            organization_id=org.id,
            user_id=owner.id,
            org_role="owner",
            status="active",
            joined_at=datetime.now(UTC),
        )

        # Assign RBAC system role (best-effort — OK if role not seeded yet)
        owner_role = await self.role_repo.get_system_role_by_name("owner")
        if owner_role:
            await self.org_user_role_repo.assign(org_user.id, owner_role.id, owner.id)

        await self.audit.log(
            action="org.created",
            resource_type="organization",
            resource_id=org.id,
            org_id=org.id,
            actor_user_id=owner.id,
            request=request,
            new_values={"name": org.name, "slug": slug},
            description=f"Organization '{org.name}' created",
        )

        await self.session.commit()
        return OrgResponse.model_validate(org)

    async def get_organization_by_slug(
        self, slug: str, user: User
    ) -> OrgResponse:
        org = await self.org_repo.get_by_slug(slug)
        if not org:
            raise NotFoundException("Organization not found")
        await self._get_member(org.id, user.id)
        return OrgResponse.model_validate(org)

    async def get_organization(self, org_id: UUID, user: User) -> OrgResponse:
        org = await self._get_org_or_404(org_id)
        await self._get_member(org_id, user.id)
        return OrgResponse.model_validate(org)

    async def update_organization(
        self,
        org_id: UUID,
        data: UpdateOrgRequest,
        user: User,
        request: Request,
    ) -> OrgResponse:
        org = await self._get_org_or_404(org_id)
        ou = await self._get_member(org_id, user.id)
        self._require_role(ou, "admin")

        patches = data.model_dump(exclude_none=True)
        if not patches:
            return OrgResponse.model_validate(org)

        old_values = {k: getattr(org, k, None) for k in patches}
        updated = await self.org_repo.update(org_id, **patches)

        await self.audit.log(
            action="org.updated",
            resource_type="organization",
            resource_id=org_id,
            org_id=org_id,
            actor_user_id=user.id,
            request=request,
            old_values={k: str(v) for k, v in old_values.items()},
            new_values={k: str(v) for k, v in patches.items()},
            description=f"Organization '{org.name}' updated",
        )

        await self.session.commit()
        return OrgResponse.model_validate(updated)

    async def delete_organization(
        self, org_id: UUID, user: User, request: Request
    ) -> None:
        org = await self._get_org_or_404(org_id)
        ou = await self._get_member(org_id, user.id)
        self._require_role(ou, "owner")

        await self.org_repo.soft_delete(org_id)

        await self.audit.log(
            action="org.deleted",
            resource_type="organization",
            resource_id=org_id,
            org_id=org_id,
            actor_user_id=user.id,
            request=request,
            description=f"Organization '{org.name}' soft-deleted",
        )

        await self.session.commit()

    # ── Member management ─────────────────────────────────────────────────

    async def list_members(
        self,
        org_id: UUID,
        user: User,
        params: PaginationParams,
    ) -> MemberListResponse:
        await self._get_org_or_404(org_id)
        await self._get_member(org_id, user.id)

        members, total = await self.org_user_repo.list_with_users(
            org_id, offset=params.offset, limit=params.limit
        )

        total_pages = math.ceil(total / params.page_size) if total else 0

        return MemberListResponse(
            members=[_build_member_response(m) for m in members],
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
        )

    async def remove_member(
        self,
        org_id: UUID,
        target_user_id: UUID,
        actor: User,
        request: Request,
    ) -> None:
        await self._get_org_or_404(org_id)
        actor_ou = await self._get_member(org_id, actor.id)
        self._require_role(actor_ou, "admin")

        target_ou = await self.org_user_repo.get_by_org_and_user(
            org_id, target_user_id
        )
        if not target_ou:
            raise NotFoundException("Member not found in this organization")

        # Admins cannot remove owners unless they are the owner themselves
        if target_ou.org_role == "owner" and actor_ou.org_role != "owner":
            raise ForbiddenException("Only an owner can remove another owner")

        await self.org_user_repo.remove(target_ou.id)

        await self.audit.log(
            action="org.member.removed",
            resource_type="organization_user",
            resource_id=target_ou.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            description=f"Member {target_user_id} removed from org {org_id}",
        )

        await self.session.commit()

    async def update_member_role(
        self,
        org_id: UUID,
        target_user_id: UUID,
        data: UpdateMemberRoleRequest,
        actor: User,
        request: Request,
    ) -> MemberResponse:
        await self._get_org_or_404(org_id)
        actor_ou = await self._get_member(org_id, actor.id)
        self._require_role(actor_ou, "admin")

        target_ou = await self.org_user_repo.get_by_org_and_user(
            org_id, target_user_id
        )
        if not target_ou:
            raise NotFoundException("Member not found in this organization")

        # Cannot promote to owner unless actor is owner
        if data.org_role == "owner" and actor_ou.org_role != "owner":
            raise ForbiddenException("Only an owner can assign the owner role")

        old_role = target_ou.org_role
        await self.org_user_repo.update_role(target_ou.id, data.org_role)

        await self.audit.log(
            action="org.member.role_changed",
            resource_type="organization_user",
            resource_id=target_ou.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            old_values={"org_role": old_role},
            new_values={"org_role": data.org_role},
            description=f"Member {target_user_id} role changed {old_role} → {data.org_role}",
        )

        await self.session.commit()

        # After commit, reload the member with user relationship using
        # populate_existing=True to bypass the SQLAlchemy identity-map cache.
        refreshed = await self.org_user_repo.get_by_id_with_user(target_ou.id)
        if refreshed is None:
            raise NotFoundException("Member not found after update")
        return _build_member_response(refreshed)

    # ── Invitations ───────────────────────────────────────────────────────

    async def invite_member(
        self,
        org_id: UUID,
        data: InviteRequest,
        inviter: User,
        request: Request,
    ) -> InvitationResponse:
        org = await self._get_org_or_404(org_id)
        inviter_ou = await self._get_member(org_id, inviter.id)
        self._require_role(inviter_ou, "admin")

        # Seat-limit check (counts existing members + pending invites)
        await self._check_seat_limit(org)

        email = data.email.lower()

        # Check if already a member
        from app.modules.auth.repository import UserRepository
        user_repo = UserRepository(User, self.session)
        existing_user = await user_repo.get_by_email(email)
        if existing_user:
            already_member = await self.org_user_repo.get_by_org_and_user(
                org_id, existing_user.id
            )
            if already_member and already_member.status not in ("deactivated",):
                raise ConflictException("User is already a member of this organization")

        # Check for pending duplicate invite
        existing_invite = await self.invitation_repo.get_pending_by_email_and_org(
            email, org_id
        )
        if existing_invite:
            raise ConflictException(
                "A pending invitation for this email already exists"
            )

        token = secrets.token_urlsafe(32)
        invitation = await self.invitation_repo.create(
            organization_id=org_id,
            email=email,
            token=token,
            org_role=data.org_role,
            invited_by=inviter.id,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(days=_INVITE_TTL_DAYS),
        )

        # Fire-and-forget email (Celery task placeholder)
        logger.info(
            "Invitation created — email would be sent here",
            email=email,
            org_id=str(org_id),
            token=token[:8] + "…",
        )

        await self.audit.log(
            action="org.member.invited",
            resource_type="invitation",
            resource_id=invitation.id,
            org_id=org_id,
            actor_user_id=inviter.id,
            request=request,
            new_values={"email": email, "org_role": data.org_role},
            description=f"{email} invited to org {org_id} as {data.org_role}",
        )

        await self.session.commit()
        return InvitationResponse.model_validate(invitation)

    async def list_invitations(
        self,
        org_id: UUID,
        user: User,
        params: PaginationParams,
    ) -> list[InvitationResponse]:
        await self._get_org_or_404(org_id)
        ou = await self._get_member(org_id, user.id)
        self._require_role(ou, "admin")

        invitations, _ = await self.invitation_repo.list_pending(
            org_id, offset=params.offset, limit=params.limit
        )
        return [InvitationResponse.model_validate(i) for i in invitations]

    async def revoke_invitation(
        self,
        org_id: UUID,
        invitation_id: UUID,
        user: User,
        request: Request,
    ) -> None:
        await self._get_org_or_404(org_id)
        ou = await self._get_member(org_id, user.id)
        self._require_role(ou, "admin")

        inv = await self.invitation_repo.get_by_id(invitation_id)
        if not inv or inv.organization_id != org_id:
            raise NotFoundException("Invitation not found")
        if inv.status != "pending":
            raise BadRequestException(
                f"Invitation is already {inv.status} and cannot be revoked"
            )

        await self.invitation_repo.revoke(invitation_id)

        await self.audit.log(
            action="org.invitation.revoked",
            resource_type="invitation",
            resource_id=invitation_id,
            org_id=org_id,
            actor_user_id=user.id,
            request=request,
            description=f"Invitation for {inv.email} revoked",
        )

        await self.session.commit()

    async def accept_invitation(
        self,
        data: AcceptInvitationRequest,
        user: User,
        request: Request,
    ) -> OrgResponse:
        """Accept a pending invitation.  The accepting user must be authenticated."""
        inv = await self.invitation_repo.get_by_token(data.token)
        if not inv:
            raise NotFoundException("Invitation not found or invalid token")
        if inv.status != "pending":
            raise BadRequestException(
                f"This invitation is already {inv.status}"
            )
        if inv.expires_at < datetime.now(UTC):
            await self.invitation_repo.revoke(inv.id)
            await self.session.commit()
            raise BadRequestException("Invitation has expired")
        if inv.email.lower() != user.email.lower():
            raise ForbiddenException(
                "This invitation was sent to a different email address"
            )

        org = await self._get_org_or_404(inv.organization_id)

        # Check the user isn't already an active member
        existing = await self.org_user_repo.get_by_org_and_user(
            inv.organization_id, user.id
        )
        if existing and existing.status not in ("deactivated",):
            raise ConflictException("You are already a member of this organization")

        # Seat check
        await self._check_seat_limit(org)

        org_user = await self.org_user_repo.create(
            organization_id=inv.organization_id,
            user_id=user.id,
            org_role=inv.org_role,
            status="active",
            joined_at=datetime.now(UTC),
            invited_by=inv.invited_by,
        )

        # Assign RBAC role (best-effort)
        system_role = await self.role_repo.get_system_role_by_name(inv.org_role)
        if system_role:
            await self.org_user_role_repo.assign(org_user.id, system_role.id, None)

        await self.invitation_repo.accept(inv.id)

        await self.audit.log(
            action="org.invitation.accepted",
            resource_type="invitation",
            resource_id=inv.id,
            org_id=inv.organization_id,
            actor_user_id=user.id,
            request=request,
            description=f"{user.email} accepted invitation to org {inv.organization_id}",
        )

        await self.session.commit()
        return OrgResponse.model_validate(org)

    # ── Domain verification ───────────────────────────────────────────────

    async def add_domain(
        self,
        org_id: UUID,
        data: AddDomainRequest,
        user: User,
        request: Request,
    ) -> DomainResponse:
        await self._get_org_or_404(org_id)
        ou = await self._get_member(org_id, user.id)
        self._require_role(ou, "admin")

        # Global uniqueness — a domain can only belong to one org
        existing = await self.domain_repo.get_by_domain(data.domain)
        if existing:
            if existing.organization_id == org_id:
                raise ConflictException("Domain is already registered for this organization")
            raise ConflictException(
                "Domain is already claimed by another organization"
            )

        # Generate TXT verification token
        token = f"saas-verify={secrets.token_hex(16)}"

        domain_record = await self.domain_repo.create(
            organization_id=org_id,
            domain=data.domain,
            is_verified=False,
            verification_token=token,
        )

        await self.audit.log(
            action="org.domain.added",
            resource_type="organization_domain",
            resource_id=domain_record.id,
            org_id=org_id,
            actor_user_id=user.id,
            request=request,
            new_values={"domain": data.domain},
            description=f"Domain {data.domain} added (pending verification)",
        )

        await self.session.commit()
        return DomainResponse.model_validate(domain_record)

    async def list_domains(self, org_id: UUID, user: User) -> list[DomainResponse]:
        await self._get_org_or_404(org_id)
        await self._get_member(org_id, user.id)
        domains = await self.domain_repo.list_by_org(org_id)
        return [DomainResponse.model_validate(d) for d in domains]

    async def verify_domain(
        self,
        org_id: UUID,
        domain_id: UUID,
        user: User,
        request: Request,
    ) -> DomainResponse:
        await self._get_org_or_404(org_id)
        ou = await self._get_member(org_id, user.id)
        self._require_role(ou, "admin")

        domain_record = await self.domain_repo.get_by_id(domain_id)
        if not domain_record or domain_record.organization_id != org_id:
            raise NotFoundException("Domain not found")
        if domain_record.is_verified:
            raise BadRequestException("Domain is already verified")

        token = domain_record.verification_token
        domain = domain_record.domain
        verified = await _dns_txt_verify(domain, token)

        if not verified:
            raise BadRequestException(
                f"DNS TXT record not found. Please add the following TXT record "
                f"to {_DNS_TXT_PREFIX}.{domain}: '{token}'"
            )

        await self.domain_repo.update(
            domain_id,
            is_verified=True,
            verified_at=datetime.now(UTC),
        )

        await self.audit.log(
            action="org.domain.verified",
            resource_type="organization_domain",
            resource_id=domain_id,
            org_id=org_id,
            actor_user_id=user.id,
            request=request,
            description=f"Domain {domain} verified successfully",
        )

        await self.session.commit()
        updated = await self.domain_repo.get_by_id(domain_id)
        return DomainResponse.model_validate(updated)

    async def delete_domain(
        self,
        org_id: UUID,
        domain_id: UUID,
        user: User,
        request: Request,
    ) -> None:
        await self._get_org_or_404(org_id)
        ou = await self._get_member(org_id, user.id)
        self._require_role(ou, "admin")

        domain_record = await self.domain_repo.get_by_id(domain_id)
        if not domain_record or domain_record.organization_id != org_id:
            raise NotFoundException("Domain not found")

        await self.domain_repo.delete(domain_id)

        await self.audit.log(
            action="org.domain.deleted",
            resource_type="organization_domain",
            resource_id=domain_id,
            org_id=org_id,
            actor_user_id=user.id,
            request=request,
            description=f"Domain {domain_record.domain} deleted",
        )

        await self.session.commit()


# ── Module-level helpers ──────────────────────────────────────────────────

def _build_member_response(ou: OrganizationUser) -> MemberResponse:
    """Convert an OrganizationUser (with .user loaded) to MemberResponse."""
    user = ou.user  # must be selectinload-ed
    return MemberResponse(
        id=ou.id,
        organization_id=ou.organization_id,
        user=UserBrief(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        ),
        org_role=ou.org_role,
        status=ou.status,
        joined_at=ou.joined_at,
        created_at=ou.created_at,
        suspended_at=ou.suspended_at,
        suspension_reason=ou.suspension_reason,
    )


async def _dns_txt_verify(domain: str, expected_token: str | None) -> bool:
    """
    Resolve TXT records for ``_saas-verify.<domain>`` and check for
    the expected verification token.  Returns False on any DNS error.
    """
    if not expected_token:
        return False
    txt_name = f"{_DNS_TXT_PREFIX}.{domain}"
    try:
        answers = await dns.asyncresolver.resolve(txt_name, "TXT")
        for rdata in answers:
            for string in rdata.strings:
                value = string.decode("utf-8", errors="replace") if isinstance(string, bytes) else string
                if value == expected_token:
                    return True
    except Exception as exc:  # NXDOMAIN, Timeout, etc.
        logger.debug("DNS TXT lookup failed", domain=txt_name, error=str(exc))
    return False

"""
Tenancy module repositories.

OrganizationRepository       — org CRUD + slug lookups
OrganizationUserRepository   — membership management
InvitationRepository         — invitation lifecycle
OrganizationDomainRepository — domain add / verify / delete
"""

from __future__ import annotations

import math
from datetime import datetime, UTC
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.tenancy.models import (
    Invitation,
    Organization,
    OrganizationDomain,
    OrganizationUser,
)
from app.modules.auth.models import User


# ── OrganizationRepository ────────────────────────────────────────────────

class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, org_id: UUID) -> Organization | None:
        result = await self.session.execute(
            select(Organization).where(
                Organization.id == org_id,
                Organization.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(
            select(Organization).where(
                Organization.slug == slug,
                Organization.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(Organization)
            .where(Organization.slug == slug)
        )
        return result.scalar_one() > 0

    async def create(self, **kwargs) -> Organization:
        org = Organization(**kwargs)
        self.session.add(org)
        await self.session.flush()
        await self.session.refresh(org)
        return org

    async def update(self, org_id: UUID, **kwargs) -> Organization | None:
        await self.session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(**kwargs, updated_at=datetime.now(UTC))
        )
        await self.session.flush()
        return await self.get_by_id(org_id)

    async def soft_delete(self, org_id: UUID) -> None:
        await self.session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(deleted_at=datetime.now(UTC), is_active=False)
        )
        await self.session.flush()

    async def get_first_active_org(self) -> UUID | None:
        """Return the id of the first active org in the system (for platform admin fallback)."""
        result = await self.session.execute(
            select(Organization.id)
            .where(
                Organization.deleted_at.is_(None),
                Organization.is_active.is_(True),
            )
            .order_by(Organization.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()


# ── OrganizationUserRepository ────────────────────────────────────────────

class OrganizationUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_org_and_user(
        self, org_id: UUID, user_id: UUID
    ) -> OrganizationUser | None:
        result = await self.session.execute(
            select(OrganizationUser).where(
                OrganizationUser.organization_id == org_id,
                OrganizationUser.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, member_id: UUID) -> OrganizationUser | None:
        result = await self.session.execute(
            select(OrganizationUser).where(OrganizationUser.id == member_id)
        )
        return result.scalar_one_or_none()

    async def get_first_active_org_for_user(self, user_id: UUID) -> UUID | None:
        """Return the organization_id of the user's first active membership, or None."""
        result = await self.session.execute(
            select(OrganizationUser.organization_id)
            .join(
                Organization,
                Organization.id == OrganizationUser.organization_id,
            )
            .where(
                OrganizationUser.user_id == user_id,
                OrganizationUser.status == "active",
                Organization.deleted_at.is_(None),
                Organization.is_active.is_(True),
            )
            .order_by(OrganizationUser.joined_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> OrganizationUser:
        ou = OrganizationUser(**kwargs)
        self.session.add(ou)
        await self.session.flush()
        await self.session.refresh(ou)
        return ou

    async def count_active(self, org_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(OrganizationUser)
            .where(
                OrganizationUser.organization_id == org_id,
                OrganizationUser.status.in_(["active", "invited"]),
            )
        )
        return result.scalar_one()

    async def list_with_users(
        self,
        org_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[OrganizationUser], int]:
        """Return (members_page, total_count) with user relationship loaded."""
        count_result = await self.session.execute(
            select(func.count())
            .select_from(OrganizationUser)
            .where(
                OrganizationUser.organization_id == org_id,
                OrganizationUser.status != "deactivated",
            )
        )
        total = count_result.scalar_one()

        rows_result = await self.session.execute(
            select(OrganizationUser)
            .where(
                OrganizationUser.organization_id == org_id,
                OrganizationUser.status != "deactivated",
            )
            .options(selectinload(OrganizationUser.user))
            .offset(offset)
            .limit(limit)
            .order_by(OrganizationUser.joined_at)
        )
        members = rows_result.scalars().all()
        return members, total

    async def update_role(self, member_id: UUID, org_role: str) -> None:
        await self.session.execute(
            update(OrganizationUser)
            .where(OrganizationUser.id == member_id)
            .values(org_role=org_role)
        )

    async def get_by_id_with_user(self, member_id: UUID) -> OrganizationUser | None:
        """Fetch a single OrganizationUser with its user relationship loaded."""
        result = await self.session.execute(
            select(OrganizationUser)
            .where(OrganizationUser.id == member_id)
            .options(selectinload(OrganizationUser.user))
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
        await self.session.flush()

    async def suspend(
        self, member_id: UUID, reason: str | None = None
    ) -> None:
        await self.session.execute(
            update(OrganizationUser)
            .where(OrganizationUser.id == member_id)
            .values(
                status="suspended",
                suspended_at=datetime.now(UTC),
                suspension_reason=reason,
            )
        )
        await self.session.flush()

    async def remove(self, member_id: UUID) -> None:
        """Mark membership as deactivated (soft remove)."""
        await self.session.execute(
            update(OrganizationUser)
            .where(OrganizationUser.id == member_id)
            .values(status="deactivated")
        )
        await self.session.flush()


# ── InvitationRepository ──────────────────────────────────────────────────

class InvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_token(self, token: str) -> Invitation | None:
        result = await self.session.execute(
            select(Invitation).where(Invitation.token == token)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, invitation_id: UUID) -> Invitation | None:
        result = await self.session.execute(
            select(Invitation).where(Invitation.id == invitation_id)
        )
        return result.scalar_one_or_none()

    async def get_pending_by_email_and_org(
        self, email: str, org_id: UUID
    ) -> Invitation | None:
        result = await self.session.execute(
            select(Invitation).where(
                Invitation.organization_id == org_id,
                Invitation.email == email.lower(),
                Invitation.status == "pending",
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> Invitation:
        inv = Invitation(**kwargs)
        self.session.add(inv)
        await self.session.flush()
        await self.session.refresh(inv)
        return inv

    async def list_pending(
        self, org_id: UUID, *, offset: int = 0, limit: int = 50
    ) -> tuple[Sequence[Invitation], int]:
        count_result = await self.session.execute(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.organization_id == org_id,
                Invitation.status == "pending",
            )
        )
        total = count_result.scalar_one()

        rows_result = await self.session.execute(
            select(Invitation)
            .where(
                Invitation.organization_id == org_id,
                Invitation.status == "pending",
            )
            .offset(offset)
            .limit(limit)
            .order_by(Invitation.created_at.desc())
        )
        return rows_result.scalars().all(), total

    async def revoke(self, invitation_id: UUID) -> None:
        await self.session.execute(
            update(Invitation)
            .where(Invitation.id == invitation_id)
            .values(status="revoked")
        )
        await self.session.flush()

    async def accept(self, invitation_id: UUID) -> None:
        await self.session.execute(
            update(Invitation)
            .where(Invitation.id == invitation_id)
            .values(status="accepted", accepted_at=datetime.now(UTC))
        )
        await self.session.flush()

    async def expire_stale(self) -> int:
        """Mark all past-deadline pending invitations as expired."""
        from sqlalchemy import and_
        result = await self.session.execute(
            update(Invitation)
            .where(
                Invitation.status == "pending",
                Invitation.expires_at < datetime.now(UTC),
            )
            .values(status="expired")
        )
        await self.session.flush()
        return result.rowcount  # type: ignore[attr-defined]


# ── OrganizationDomainRepository ──────────────────────────────────────────

class OrganizationDomainRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, domain_id: UUID) -> OrganizationDomain | None:
        result = await self.session.execute(
            select(OrganizationDomain).where(OrganizationDomain.id == domain_id)
        )
        return result.scalar_one_or_none()

    async def get_by_domain(self, domain: str) -> OrganizationDomain | None:
        result = await self.session.execute(
            select(OrganizationDomain).where(
                OrganizationDomain.domain == domain.lower()
            )
        )
        return result.scalar_one_or_none()

    async def list_by_org(self, org_id: UUID) -> Sequence[OrganizationDomain]:
        result = await self.session.execute(
            select(OrganizationDomain)
            .where(OrganizationDomain.organization_id == org_id)
            .order_by(OrganizationDomain.domain)
        )
        return result.scalars().all()

    async def create(self, **kwargs) -> OrganizationDomain:
        d = OrganizationDomain(**kwargs)
        self.session.add(d)
        await self.session.flush()
        await self.session.refresh(d)
        return d

    async def update(self, domain_id: UUID, **kwargs) -> None:
        await self.session.execute(
            update(OrganizationDomain)
            .where(OrganizationDomain.id == domain_id)
            .values(**kwargs)
        )
        await self.session.flush()

    async def delete(self, domain_id: UUID) -> None:
        from sqlalchemy import delete
        await self.session.execute(
            delete(OrganizationDomain).where(OrganizationDomain.id == domain_id)
        )
        await self.session.flush()

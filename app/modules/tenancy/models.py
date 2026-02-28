"""
Tenancy module ORM models.

Tables: organizations, organization_domains, organization_users, invitations
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import SoftDeleteMixin, TimestampMixin


# ── Organization ──────────────────────────────────────────────────────────

class Organization(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # Owner
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Org-level config
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    # Limits
    max_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    members: Mapped[list["OrganizationUser"]] = relationship(
        "OrganizationUser", back_populates="organization", cascade="all, delete-orphan", lazy="noload"
    )
    domains: Mapped[list["OrganizationDomain"]] = relationship(
        "OrganizationDomain", back_populates="organization", cascade="all, delete-orphan", lazy="noload"
    )
    invitations: Mapped[list["Invitation"]] = relationship(
        "Invitation", back_populates="organization", cascade="all, delete-orphan", lazy="noload"
    )

    __table_args__ = (
        Index("ix_organizations_is_active", "is_active"),
        Index("ix_organizations_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug}>"


# ── OrganizationDomain ────────────────────────────────────────────────────

class OrganizationDomain(Base, TimestampMixin):
    __tablename__ = "organization_domains"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="domains", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "domain", name="uq_org_domain"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationDomain domain={self.domain}>"


# ── OrganizationUser ──────────────────────────────────────────────────────

class OrganizationUser(Base, TimestampMixin):
    __tablename__ = "organization_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Quick-access role (owner | admin | member | viewer)
    org_role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)

    status: Mapped[str] = mapped_column(
        String(50), default="active", nullable=False, index=True
    )  # invited | active | suspended | deactivated

    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="members", lazy="noload"
    )
    user: Mapped["User"] = relationship(
        "User", back_populates="organization_users", lazy="noload"
    )
    role_assignments: Mapped[list["OrganizationUserRole"]] = relationship(
        "OrganizationUserRole", back_populates="organization_user", cascade="all, delete-orphan", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_user"),
        Index("ix_organization_users_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationUser org={self.organization_id} user={self.user_id}>"


# ── Invitation ────────────────────────────────────────────────────────────

class Invitation(Base, TimestampMixin):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    org_role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False
    )  # pending | accepted | expired | revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="invitations", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_invitation_org_email"),
        Index("ix_invitations_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Invitation email={self.email} status={self.status}>"

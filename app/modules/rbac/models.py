"""
RBAC module ORM models.

Tables: roles, permissions, role_permissions, organization_user_roles
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
from app.shared.base_models import TimestampMixin


# ── Role ──────────────────────────────────────────────────────────────────

class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )  # NULL = global/system role
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan", lazy="noload"
    )
    user_assignments: Mapped[list["OrganizationUserRole"]] = relationship(
        "OrganizationUserRole", back_populates="role", cascade="all, delete-orphan", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint("name", "organization_id", name="uq_role_name_org"),
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name}>"


# ── Permission ────────────────────────────────────────────────────────────

class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    module: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="permission", cascade="all, delete-orphan", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint("module", "resource", "action", name="uq_permission_module_resource_action"),
    )

    def __repr__(self) -> str:
        return f"<Permission name={self.name}>"


# ── RolePermission ────────────────────────────────────────────────────────

class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions", lazy="noload")
    permission: Mapped["Permission"] = relationship(
        "Permission", back_populates="role_permissions", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<RolePermission role={self.role_id} perm={self.permission_id}>"


# ── OrganizationUserRole ──────────────────────────────────────────────────

class OrganizationUserRole(Base):
    __tablename__ = "organization_user_roles"

    organization_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization_users.id", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Relationships
    organization_user: Mapped["OrganizationUser"] = relationship(
        "OrganizationUser", back_populates="role_assignments", lazy="noload"
    )
    role: Mapped["Role"] = relationship("Role", back_populates="user_assignments", lazy="noload")

    def __repr__(self) -> str:
        return f"<OrganizationUserRole org_user={self.organization_user_id} role={self.role_id}>"

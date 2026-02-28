"""
Auth module ORM models.

Tables: users, sessions, verification_tokens,
        two_factor_backup_codes, user_oauth_accounts
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
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import SoftDeleteMixin, TimestampMixin


# ── User ──────────────────────────────────────────────────────────────────

class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Identity
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Platform flags
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Email verification
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 2FA
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_method: Mapped[str | None] = mapped_column(String(50), nullable=True)  # totp | sms | email
    two_factor_secret: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted TOTP secret

    # Password policy
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Security
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    account_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Activity tracking
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Preferences
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    # Relationships
    organization_users: Mapped[list["OrganizationUser"]] = relationship(
        "OrganizationUser", back_populates="user", lazy="noload"
    )
    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )
    verification_tokens: Mapped[list["VerificationToken"]] = relationship(
        "VerificationToken", back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )
    two_factor_backup_codes: Mapped[list["TwoFactorBackupCode"]] = relationship(
        "TwoFactorBackupCode", back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )
    oauth_accounts: Mapped[list["UserOAuthAccount"]] = relationship(
        "UserOAuthAccount", back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )

    __table_args__ = (
        Index("ix_users_email_active", "email", "is_active"),
        Index("ix_users_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"


# ── Session ───────────────────────────────────────────────────────────────

class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # desktop | mobile | tablet | api
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions", lazy="noload")

    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id} user_id={self.user_id}>"


# ── VerificationToken ─────────────────────────────────────────────────────

class VerificationToken(Base, TimestampMixin):
    __tablename__ = "verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # email_verification | password_reset | magic_link
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="verification_tokens", lazy="noload")

    __table_args__ = (
        Index("ix_verification_tokens_user_type", "user_id", "type"),
    )

    def __repr__(self) -> str:
        return f"<VerificationToken id={self.id} type={self.type}>"


# ── TwoFactorBackupCode ───────────────────────────────────────────────────

class TwoFactorBackupCode(Base, TimestampMixin):
    __tablename__ = "two_factor_backup_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)  # argon2 hashed backup code
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="two_factor_backup_codes", lazy="noload")

    def __repr__(self) -> str:
        return f"<TwoFactorBackupCode id={self.id} user_id={self.user_id}>"


# ── UserOAuthAccount ──────────────────────────────────────────────────────

class UserOAuthAccount(Base, TimestampMixin):
    __tablename__ = "user_oauth_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # google | github | microsoft | saml
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)   # encrypted
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="oauth_accounts", lazy="noload")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
    )

    def __repr__(self) -> str:
        return f"<UserOAuthAccount provider={self.provider} user_id={self.user_id}>"

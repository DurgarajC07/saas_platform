"""
Security module ORM models.

Tables: login_attempts, blocked_ips
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base_models import TimestampMixin


# ── LoginAttempt ──────────────────────────────────────────────────────────────
class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    ip_address: Mapped[str] = mapped_column(INET, nullable=False, index=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(
        String(50), default="password", nullable=False
    )  # password | oauth | magic_link | 2fa
    is_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # invalid_password | account_locked | 2fa_failed
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_login_attempts_email", "email"),
        Index("ix_login_attempts_ip", "ip_address"),
        Index("ix_login_attempts_at", "attempted_at"),
    )

    def __repr__(self) -> str:
        return f"<LoginAttempt email={self.email} success={self.is_success}>"


# ── BlockedIP ─────────────────────────────────────────────────────────────────
class BlockedIP(Base, TimestampMixin):
    __tablename__ = "blocked_ips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ip_address: Mapped[str] = mapped_column(INET, unique=True, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # NULL = permanent
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<BlockedIP ip={self.ip_address} active={self.is_active}>"

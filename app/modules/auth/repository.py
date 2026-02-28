"""
Auth module repositories.

UserRepository          — extends BaseRepository[User]; adds auth-specific queries
VerificationTokenRepository — manages email-verify and password-reset tokens
SessionRepository       — manages DB session rows (refresh-token tracking)

Repositories contain only data-access logic — no business rules.
Commits are the responsibility of the calling service.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import (
    Session,
    TwoFactorBackupCode,
    User,
    UserOAuthAccount,
    VerificationToken,
)
from app.shared.base_repository import BaseRepository


# ── UserRepository ─────────────────────────────────────────────────────────

class UserRepository(BaseRepository[User]):
    """Data-access layer for the users table."""

    async def get_by_email(self, email: str) -> User | None:
        """Return an active (non-deleted) user by email, or None."""
        result = await self.session.execute(
            select(User).where(
                User.email == email,
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_by_id(self, user_id: UUID) -> User | None:
        """Return a user only if active and not deleted."""
        result = await self.session.execute(
            select(User).where(
                User.id == user_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def increment_failed_attempts(self, user_id: UUID) -> None:
        """Atomically increment failed_login_attempts for a user."""
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(failed_login_attempts=User.failed_login_attempts + 1)
        )
        await self.session.flush()


# ── VerificationTokenRepository ────────────────────────────────────────────

class VerificationTokenRepository:
    """
    Data-access layer for the verification_tokens table.

    Not an extension of BaseRepository because VerificationToken has no
    deleted_at column — rows are expired via expires_at / used_at instead.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> VerificationToken:
        token = VerificationToken(**kwargs)
        self.session.add(token)
        await self.session.flush()
        await self.session.refresh(token)
        return token

    async def get_valid_by_hash(
        self, token_hash: str, token_type: str
    ) -> VerificationToken | None:
        """
        Return a token only if it:
        - matches the hash and type
        - has not been used (used_at IS NULL)
        - has not expired (expires_at > now)
        """
        result = await self.session.execute(
            select(VerificationToken).where(
                VerificationToken.token_hash == token_hash,
                VerificationToken.type == token_type,
                VerificationToken.used_at.is_(None),
                VerificationToken.expires_at > func.now(),
            )
        )
        return result.scalar_one_or_none()

    async def mark_used(self, token_id: UUID) -> None:
        """Stamp used_at to prevent token reuse."""
        await self.session.execute(
            update(VerificationToken)
            .where(VerificationToken.id == token_id)
            .values(used_at=datetime.now(UTC))
        )
        await self.session.flush()

    async def invalidate_all(self, user_id: UUID, token_type: str) -> None:
        """
        Mark all active tokens of a given type for a user as used.
        Called before issuing a fresh token of the same type (e.g. password reset).
        """
        await self.session.execute(
            update(VerificationToken)
            .where(
                VerificationToken.user_id == user_id,
                VerificationToken.type == token_type,
                VerificationToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )
        await self.session.flush()


# ── SessionRepository ──────────────────────────────────────────────────────

class SessionRepository:
    """
    Data-access layer for the sessions table (refresh-token tracking).

    Not an extension of BaseRepository because Session has no deleted_at;
    sessions are invalidated via revoked_at instead.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> Session:
        db_session = Session(**kwargs)
        self.session.add(db_session)
        await self.session.flush()
        await self.session.refresh(db_session)
        return db_session

    async def get_active_by_token_hash(self, token_hash: str) -> Session | None:
        """Return a non-revoked, non-expired session by token hash."""
        result = await self.session.execute(
            select(Session).where(
                Session.token_hash == token_hash,
                Session.revoked_at.is_(None),
                Session.expires_at > func.now(),
            )
        )
        return result.scalar_one_or_none()

    async def revoke_by_token_hash(self, token_hash: str) -> None:
        """Mark a session row as revoked."""
        await self.session.execute(
            update(Session)
            .where(Session.token_hash == token_hash)
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        """Revoke every active session belonging to a user (e.g. password change)."""
        await self.session.execute(
            update(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.flush()

    async def list_active_for_user(self, user_id: UUID) -> list[Session]:
        """Return all non-revoked, non-expired sessions for a user, newest first."""
        result = await self.session.execute(
            select(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
                Session.expires_at > func.now(),
            )
            .order_by(Session.last_active_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, session_id: UUID) -> Session | None:
        """Return a session row by its primary key."""
        result = await self.session.execute(
            select(Session).where(Session.id == session_id)
        )
        return result.scalar_one_or_none()

    async def revoke_by_id(self, session_id: UUID) -> None:
        """Revoke a specific session row by ID."""
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.flush()

    async def revoke_all_except(
        self, user_id: UUID, current_session_id: UUID
    ) -> None:
        """Revoke every active session for a user except the current one."""
        await self.session.execute(
            update(Session)
            .where(
                Session.user_id == user_id,
                Session.id != current_session_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.flush()


# ── OAuthAccountRepository ─────────────────────────────────────────────────────

class OAuthAccountRepository:
    """
    Data-access layer for user_oauth_accounts.
    Handles linking social login identities to platform users.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_provider(
        self, provider: str, provider_user_id: str
    ) -> UserOAuthAccount | None:
        """Return an OAuth account row by provider + provider-side user ID."""
        result = await self.session.execute(
            select(UserOAuthAccount).where(
                UserOAuthAccount.provider == provider,
                UserOAuthAccount.provider_user_id == provider_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs: Any) -> UserOAuthAccount:
        obj = UserOAuthAccount(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def get_by_user_and_provider(
        self, user_id: UUID, provider: str
    ) -> UserOAuthAccount | None:
        result = await self.session.execute(
            select(UserOAuthAccount).where(
                UserOAuthAccount.user_id == user_id,
                UserOAuthAccount.provider == provider,
            )
        )
        return result.scalar_one_or_none()


# ── TwoFactorBackupCodeRepository ──────────────────────────────────────────────

class TwoFactorBackupCodeRepository:
    """Data-access layer for TOTP backup codes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_bulk(
        self, records: list[dict[str, Any]]
    ) -> list[TwoFactorBackupCode]:
        """Insert multiple backup code rows in one flush."""
        objs = [TwoFactorBackupCode(**r) for r in records]
        self.session.add_all(objs)
        await self.session.flush()
        return objs

    async def list_unused_by_user(
        self, user_id: UUID
    ) -> list[TwoFactorBackupCode]:
        """Return all unused backup codes for a user."""
        result = await self.session.execute(
            select(TwoFactorBackupCode).where(
                TwoFactorBackupCode.user_id == user_id,
                TwoFactorBackupCode.used_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_unused_by_code_hash(
        self, user_id: UUID, code_hash: str
    ) -> TwoFactorBackupCode | None:
        """Look up an unused backup code by SHA-256 hash."""
        result = await self.session.execute(
            select(TwoFactorBackupCode).where(
                TwoFactorBackupCode.user_id == user_id,
                TwoFactorBackupCode.code_hash == code_hash,
                TwoFactorBackupCode.used_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def mark_used(self, code_id: UUID) -> None:
        await self.session.execute(
            update(TwoFactorBackupCode)
            .where(TwoFactorBackupCode.id == code_id)
            .values(used_at=datetime.now(UTC))
        )
        await self.session.flush()

    async def delete_all_for_user(self, user_id: UUID) -> None:
        """Hard-delete all backup codes for a user (e.g. on 2FA disable/re-setup)."""
        await self.session.execute(
            delete(TwoFactorBackupCode).where(
                TwoFactorBackupCode.user_id == user_id
            )
        )
        await self.session.flush()


# ── LoginAttemptRepository ──────────────────────────────────────────────────────

class LoginAttemptRepository:
    """Data-access layer for the login_attempts audit table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(self, **kwargs: Any) -> None:
        """Record a login attempt (success or failure)."""
        from app.modules.security.models import LoginAttempt
        from datetime import datetime, UTC

        kwargs.setdefault("attempted_at", datetime.now(UTC))
        attempt = LoginAttempt(**kwargs)
        self.session.add(attempt)
        await self.session.flush()
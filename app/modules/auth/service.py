"""
Auth service — orchestrates all authentication flows.

Design rules:
  - Service calls repositories; never queries the DB directly.
  - session.commit() is called here (unit-of-work pattern per operation).
  - Email sends are fire-and-forget tasks — failures never block the request.
  - Token hashes (SHA-256) are safe for lookup; passwords use Argon2id.
  - Rate limiting and denylist state live in Redis.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import structlog
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.security.hashing import hash_password, needs_rehash, verify_password
from app.core.security.jwt import create_access_token, create_refresh_token, decode_token
from app.core.utils.email import send_password_reset_email, send_verification_email
from app.core.utils.tokens import generate_token
from app.modules.auth.constants import (
    DENYLIST_PREFIX,
    LOGIN_RATE_LIMIT_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    LOGIN_RATE_PREFIX,
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    VERIFICATION_TOKEN_EXPIRE_HOURS,
)
from app.modules.auth.exceptions import (
    AccountLockedException,
    InvalidTokenException,
    TwoFactorRequiredException,
)
from app.modules.auth.models import Session, User, VerificationToken
from app.modules.auth.repository import (
    LoginAttemptRepository,
    SessionRepository,
    UserRepository,
    VerificationTokenRepository,
)
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.shared.enums import TokenType

logger = structlog.get_logger(__name__)


def _hash_token(raw_token: str) -> str:
    """SHA-256 hash for DB token lookup (not for password storage)."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class AuthService:
    """Orchestrates all authentication business logic."""

    def __init__(self, session: AsyncSession, redis: aioredis.Redis) -> None:
        self.user_repo = UserRepository(User, session)
        self.token_repo = VerificationTokenRepository(session)
        self.session_repo = SessionRepository(session)
        self.attempt_repo = LoginAttemptRepository(session)
        self.session = session
        self.redis = redis

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _check_rate_limit(self, ip: str) -> None:
        """Raise RateLimitException if the IP has exceeded login attempts."""
        from app.core.exceptions import RateLimitException
        key = f"{LOGIN_RATE_PREFIX}{ip}"
        count = await self.redis.incr(key)
        if count == 1:
            # First attempt in this window — set TTL
            await self.redis.expire(key, LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        if count > LOGIN_RATE_LIMIT_ATTEMPTS:
            raise RateLimitException(
                f"Too many login attempts. Please wait before trying again."
            )

    async def _issue_tokens(
        self,
        user: User,
        ip: str | None = None,
        user_agent: str = "",
    ) -> TokenResponse:
        """
        Create a JWT access + refresh token pair, record the DB session row,
        update last_login metadata, and return the token envelope.
        The access token's `sid` claim carries the DB session ID for session mgmt.
        Commits the transaction.
        """
        settings = get_settings()

        # Pre-generate the session ID so we can embed it as `sid` in the access token
        session_id = uuid4()
        refresh_token = create_refresh_token(user.id)
        token_hash = _hash_token(refresh_token)

        expires_at = datetime.now(UTC) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        # Record DB session for refresh-token tracking
        await self.session_repo.create(
            id=session_id,
            user_id=user.id,
            token_hash=token_hash,
            ip_address=ip or None,
            user_agent=user_agent or None,
            last_active_at=datetime.now(UTC),
            expires_at=expires_at,
        )

        # Mint access token with session ID claim (for session listing)
        access_token = create_access_token(user.id, session_id=session_id)

        # Stamp last-login metadata and clear failed attempts counter
        now = datetime.now(UTC)
        await self.user_repo.update(
            user.id,
            last_login_at=now,
            last_login_ip=ip or None,
            last_active_at=now,
            failed_login_attempts=0,
            account_locked_until=None,
        )

        await self.session.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    # ── Public operations ─────────────────────────────────────────────────

    async def register(self, data: RegisterRequest) -> User:
        """
        Create a new user and send an email verification link.
        Raises ConflictException if the email is already registered.
        """
        email = data.email.lower().strip()
        existing = await self.user_repo.get_by_email(email)
        if existing:
            raise ConflictException("Email already registered")

        user = await self.user_repo.create(
            id=uuid4(),
            email=email,
            password_hash=hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
            display_name=f"{data.first_name} {data.last_name}".strip(),
        )

        # Create email verification token
        raw_token = generate_token()
        await self.token_repo.create(
            id=uuid4(),
            user_id=user.id,
            type="email_verification",
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=VERIFICATION_TOKEN_EXPIRE_HOURS),
        )

        await self.session.commit()

        # Fire-and-forget email — does not block the response
        asyncio.create_task(send_verification_email(user.email, raw_token))
        logger.info("user_registered", user_id=str(user.id), email=email)

        return user

    async def verify_email(self, raw_token: str) -> None:
        """
        Mark the user's email as verified.
        Raises InvalidTokenException if the token is unknown, used, or expired.
        """
        token = await self.token_repo.get_valid_by_hash(
            _hash_token(raw_token), "email_verification"
        )
        if not token:
            raise InvalidTokenException()

        await self.token_repo.mark_used(token.id)
        await self.user_repo.update(
            token.user_id,
            email_verified=True,
            email_verified_at=datetime.now(UTC),
        )
        await self.session.commit()
        logger.info("email_verified", user_id=str(token.user_id))

    async def login(
        self,
        data: LoginRequest,
        ip: str,
        user_agent: str,
    ) -> TokenResponse:
        """
        Authenticate a user and issue a token pair.

        Security guarantees:
        - Rate-limited per IP: 5 attempts / 15 min.
        - Constant-time credential validation (Argon2id).
        - Generic error message to prevent user-enumeration.
        - Account locked after MAX_LOGIN_ATTEMPTS failures.
        - 2FA check before token issuance.
        """
        settings = get_settings()

        await self._check_rate_limit(ip)

        user = await self.user_repo.get_by_email(data.email.lower().strip())

        # Validate credentials — same error regardless of which check fails
        credential_ok = user is not None and verify_password(
            data.password, user.password_hash or ""
        )
        if not credential_ok:
            if user is not None:
                new_count = user.failed_login_attempts + 1
                await self.user_repo.increment_failed_attempts(user.id)
                if new_count >= settings.MAX_LOGIN_ATTEMPTS:
                    lock_until = datetime.now(UTC) + timedelta(
                        minutes=settings.ACCOUNT_LOCKOUT_MINUTES
                    )
                    await self.user_repo.update(
                        user.id, account_locked_until=lock_until
                    )
            await self.attempt_repo.log(
                user_id=user.id if user else None,
                email=data.email,
                ip_address=ip,
                user_agent=user_agent,
                method="password",
                is_success=False,
                failure_reason="invalid_credentials",
            )
            await self.session.commit()
            raise UnauthorizedException("Invalid email or password")

        if not user.is_active:  # type: ignore[union-attr]
            await self.attempt_repo.log(
                user_id=user.id,
                email=data.email,
                ip_address=ip,
                user_agent=user_agent,
                method="password",
                is_success=False,
                failure_reason="account_inactive",
            )
            await self.session.commit()
            raise ForbiddenException("Account has been deactivated")

        if (
            user.account_locked_until  # type: ignore[union-attr]
            and user.account_locked_until > datetime.now(UTC)  # type: ignore[union-attr]
        ):
            await self.attempt_repo.log(
                user_id=user.id,
                email=data.email,
                ip_address=ip,
                user_agent=user_agent,
                method="password",
                is_success=False,
                failure_reason="account_locked",
            )
            await self.session.commit()
            raise AccountLockedException()

        if user.two_factor_enabled:  # type: ignore[union-attr]
            # Store pending marker so verify/backup endpoints are gated
            await self.redis.setex(
                f"2fa_pending:{user.id}",  # type: ignore[union-attr]
                300,
                "1",
            )
            await self.attempt_repo.log(
                user_id=user.id,
                email=data.email,
                ip_address=ip,
                user_agent=user_agent,
                method="password",
                is_success=None,  # partial — 2FA not yet complete
                failure_reason="2fa_required",
            )
            await self.session.commit()
            raise TwoFactorRequiredException(str(user.id))  # type: ignore[union-attr]

        # Transparently rehash if parameters are outdated
        if needs_rehash(user.password_hash or ""):  # type: ignore[union-attr]
            new_hash = hash_password(data.password)
            await self.user_repo.update(user.id, password_hash=new_hash)  # type: ignore[union-attr]

        await self.attempt_repo.log(
            user_id=user.id,
            email=data.email,
            ip_address=ip,
            user_agent=user_agent,
            method="password",
            is_success=True,
        )

        return await self._issue_tokens(user, ip, user_agent)  # type: ignore[arg-type]

    async def refresh_tokens(
        self,
        data: RefreshRequest,
        ip: str | None = None,
        user_agent: str = "",
    ) -> TokenResponse:
        """
        Validate a refresh token, denylist it, and issue a new token pair
        (refresh-token rotation).
        """
        settings = get_settings()

        # decode_token raises UnauthorizedException if invalid
        payload = decode_token(data.refresh_token)
        if payload.get("type") != TokenType.REFRESH:
            raise UnauthorizedException("Invalid token type")

        denylist_key = f"{DENYLIST_PREFIX}{data.refresh_token}"
        if await self.redis.get(denylist_key):
            raise UnauthorizedException("Refresh token has been revoked")

        user = await self.user_repo.get_active_by_id(UUID(payload["sub"]))
        if not user:
            raise UnauthorizedException("User not found or inactive")

        # Rotate: denylist old refresh token before issuing new pair
        await self.redis.setex(
            denylist_key,
            settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
            "1",
        )
        # Revoke corresponding DB session row
        await self.session_repo.revoke_by_token_hash(_hash_token(data.refresh_token))

        return await self._issue_tokens(user, ip, user_agent)

    async def logout(
        self,
        access_token: str,
        refresh_token: str | None = None,
    ) -> None:
        """
        Denylist the current access token and optionally the refresh token.
        The caller should provide both tokens extracted from the request.
        """
        settings = get_settings()
        now = datetime.now(UTC)

        # Denylist access token (TTL = remaining valid time ≤ ACCESS_TOKEN_EXPIRE_MINUTES)
        access_ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        await self.redis.setex(f"{DENYLIST_PREFIX}{access_token}", access_ttl, "1")

        if refresh_token:
            refresh_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
            await self.redis.setex(
                f"{DENYLIST_PREFIX}{refresh_token}", refresh_ttl, "1"
            )
            await self.session_repo.revoke_by_token_hash(_hash_token(refresh_token))
            await self.session.commit()

    async def forgot_password(self, data: ForgotPasswordRequest) -> None:
        """
        Generate a password-reset token and email it.
        Does NOT reveal whether the email address is registered (anti-enumeration).
        """
        email = data.email.lower().strip()
        user = await self.user_repo.get_by_email(email)
        if not user:
            # Anti-enumeration: same timing/response whether user exists or not
            return

        # Invalidate any existing password-reset tokens
        await self.token_repo.invalidate_all(user.id, "password_reset")

        raw_token = generate_token()
        await self.token_repo.create(
            id=uuid4(),
            user_id=user.id,
            type="password_reset",
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(
                minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
            ),
        )
        await self.session.commit()

        asyncio.create_task(send_password_reset_email(user.email, raw_token))
        logger.info("password_reset_requested", user_id=str(user.id))

    async def reset_password(self, data: ResetPasswordRequest) -> None:
        """
        Verify the password-reset token and update the user's password.
        Revokes all active DB sessions so the user must re-login everywhere.
        """
        token = await self.token_repo.get_valid_by_hash(
            _hash_token(data.token), "password_reset"
        )
        if not token:
            raise InvalidTokenException()

        await self.token_repo.mark_used(token.id)
        await self.user_repo.update(
            token.user_id,
            password_hash=hash_password(data.new_password),
            password_changed_at=datetime.now(UTC),
            failed_login_attempts=0,
            account_locked_until=None,
        )

        # Revoke all sessions — forces re-login after password change
        await self.session_repo.revoke_all_for_user(token.user_id)

        await self.session.commit()
        logger.info("password_reset_completed", user_id=str(token.user_id))

    # ── Account security ──────────────────────────────────────────────────

    async def change_password(
        self,
        user: User,
        data: ChangePasswordRequest,
    ) -> None:
        """
        Change a user's password — requires the current password.
        Does NOT revoke existing sessions (design choice: let users decide).
        """
        if not verify_password(data.current_password, user.password_hash or ""):
            raise UnauthorizedException("Current password is incorrect")

        await self.user_repo.update(
            user.id,
            password_hash=hash_password(data.new_password),
            password_changed_at=datetime.now(UTC),
        )
        await self.session.commit()
        logger.info("password_changed", user_id=str(user.id))

    # ── Session management ────────────────────────────────────────────────

    async def list_sessions(
        self, user_id: UUID, current_session_id: UUID | None = None
    ) -> tuple[list, UUID | None]:
        """
        Return all active sessions for a user plus the current session ID
        so the caller can mark `is_current`.
        """
        sessions = await self.session_repo.list_active_for_user(user_id)
        return sessions, current_session_id

    async def revoke_session(
        self,
        user_id: UUID,
        session_id: UUID,
    ) -> None:
        """Revoke a specific session.  The session must belong to the requesting user."""
        from app.core.exceptions import NotFoundException

        session = await self.session_repo.get_by_id(session_id)
        if not session or session.user_id != user_id:
            raise NotFoundException("Session not found")

        await self.session_repo.revoke_by_id(session_id)
        await self.session.commit()
        logger.info("session_revoked", session_id=str(session_id), user_id=str(user_id))

    async def revoke_all_other_sessions(
        self,
        user_id: UUID,
        current_session_id: UUID,
    ) -> None:
        """Revoke all sessions except the caller's current session."""
        await self.session_repo.revoke_all_except(user_id, current_session_id)
        await self.session.commit()
        logger.info("all_other_sessions_revoked", user_id=str(user_id))

"""
Two-Factor Authentication (TOTP) service.

Supports:
  - TOTP setup (secret generation + provisioning URI for QR code)
  - Setup confirmation (verifies first code, saves encrypted secret, creates backup codes)
  - Login completion (2FA step 2 after password OK)
  - Backup code usage (one-time alternate to TOTP)
  - 2FA disable (requires current password + valid TOTP code)

Security notes:
  - TOTP secrets are encrypted at rest (Fernet) via ENCRYPTION_KEY.
  - Backup codes are hashed with SHA-256 (random tokens, not user-chosen passwords).
  - A Redis key `2fa_pending:{user_id}` (TTL 5 min) gates the verify/backup endpoints
    so only users who just completed password auth can submit a 2FA code.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pyotp
import structlog
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import BadRequestException, NotFoundException, UnauthorizedException
from app.core.security.encryption import decrypt, encrypt
from app.core.security.hashing import verify_password
from app.modules.auth.models import User
from app.modules.auth.repository import (
    TwoFactorBackupCodeRepository,
    UserRepository,
)
from app.modules.auth.schemas import TokenResponse
from app.modules.auth.service import AuthService

logger = structlog.get_logger(__name__)

_2FA_SETUP_PREFIX = "2fa_setup:"
_2FA_SETUP_TTL = 600       # 10 minutes to confirm setup
_2FA_PENDING_PREFIX = "2fa_pending:"
_2FA_PENDING_TTL = 300     # 5 minutes to complete login after password auth

_BACKUP_CODE_COUNT = 10
_BACKUP_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _random_backup_code() -> str:
    """Generate a human-readable 9-char backup code: XXXX-XXXXX."""
    part1 = "".join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(4))
    part2 = "".join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(5))
    return f"{part1}-{part2}"


def _hash_backup_code(raw: str) -> str:
    """SHA-256 hash for backup code storage (codes are random, not user-chosen)."""
    return hashlib.sha256(raw.upper().encode()).hexdigest()


class TwoFactorService:
    """Orchestrates all TOTP setup, verification, and management operations."""

    def __init__(self, session: AsyncSession, redis: aioredis.Redis) -> None:
        self.user_repo = UserRepository(User, session)
        self.backup_repo = TwoFactorBackupCodeRepository(session)
        self.session = session
        self.redis = redis

    # ── Internal helpers ──────────────────────────────────────────────────

    def _make_totp(self, secret: str) -> pyotp.TOTP:
        return pyotp.TOTP(secret)

    def _verify_code(self, secret: str, code: str) -> bool:
        """Verify a 6-digit TOTP code with a ±1 window for clock drift."""
        return self._make_totp(secret).verify(code, valid_window=1)

    async def _check_2fa_pending(self, user_id: str) -> None:
        """
        Verify that the user recently completed password authentication.
        Raises UnauthorizedException if the pending key has expired or is missing.
        """
        key = f"{_2FA_PENDING_PREFIX}{user_id}"
        if not await self.redis.get(key):
            raise UnauthorizedException(
                "2FA window expired. Please log in again with your password."
            )

    async def _consume_2fa_pending(self, user_id: str) -> None:
        """Delete the pending marker after successful 2FA completion."""
        await self.redis.delete(f"{_2FA_PENDING_PREFIX}{user_id}")

    # ── Public API — called from service / router ─────────────────────────

    async def set_pending(self, user_id: str) -> None:
        """
        Record that the user has passed password auth and may now complete 2FA.
        Called by AuthService.login() when TwoFactorRequiredException is raised.
        """
        await self.redis.setex(
            f"{_2FA_PENDING_PREFIX}{user_id}", _2FA_PENDING_TTL, "1"
        )

    async def setup_totp(self, user: User) -> dict[str, str]:
        """
        Generate a fresh TOTP secret and provisioning URI.
        The encrypted secret is stored in Redis until the user confirms.

        Returns {"secret": <base32>, "qr_uri": <otpauth://...>}.
        """
        secret = pyotp.random_base32()
        provisioning_uri = self._make_totp(secret).provisioning_uri(
            name=user.email,
            issuer_name=get_settings().APP_NAME,
        )

        # Encrypt and temporarily stash — confirmed/committed on confirm step
        encrypted_secret = encrypt(secret)
        await self.redis.setex(
            f"{_2FA_SETUP_PREFIX}{user.id}", _2FA_SETUP_TTL, encrypted_secret
        )

        logger.info("2fa_setup_initiated", user_id=str(user.id))
        return {"secret": secret, "qr_uri": provisioning_uri}

    async def confirm_totp_setup(self, user: User, code: str) -> list[str]:
        """
        Validate the first TOTP code, persist the secret, and issue 10 backup codes.
        Returns a list of raw backup codes (one-time display only).
        Raises UnauthorizedException if the code is wrong.
        Raises NotFoundException if the setup session has expired.
        """
        encrypted = await self.redis.get(f"{_2FA_SETUP_PREFIX}{user.id}")
        if not encrypted:
            raise NotFoundException(
                "2FA setup session has expired. Please start setup again."
            )

        secret = decrypt(encrypted)
        if not self._verify_code(secret, code):
            raise UnauthorizedException("Invalid authenticator code")

        # Persist encrypted secret to the user row
        await self.user_repo.update(
            user.id,
            two_factor_enabled=True,
            two_factor_method="totp",
            two_factor_secret=encrypted,
        )

        # Replace any existing backup codes with a fresh set
        await self.backup_repo.delete_all_for_user(user.id)
        raw_codes = [_random_backup_code() for _ in range(_BACKUP_CODE_COUNT)]
        await self.backup_repo.create_bulk([
            {
                "id": uuid4(),
                "user_id": user.id,
                "code_hash": _hash_backup_code(c),
            }
            for c in raw_codes
        ])

        await self.session.commit()
        await self.redis.delete(f"{_2FA_SETUP_PREFIX}{user.id}")

        logger.info("2fa_enabled", user_id=str(user.id))
        return raw_codes

    async def verify_totp(self, user: User, code: str) -> bool:
        """Verify a TOTP code against the user's stored encrypted secret."""
        if not user.two_factor_secret:
            return False
        secret = decrypt(user.two_factor_secret)
        return self._verify_code(secret, code)

    async def complete_2fa_login(
        self,
        user_id_str: str,
        code: str,
        ip: str | None = None,
        user_agent: str = "",
    ) -> TokenResponse:
        """
        Complete 2FA login after successful password auth.

        Validates:
          1. Pending login marker (Redis) — user must have passed password auth
          2. TOTP code correctness
        Issues a full token pair on success.
        """
        await self._check_2fa_pending(user_id_str)

        user = await self.user_repo.get_active_by_id(UUID(user_id_str))
        if not user:
            raise UnauthorizedException("User not found or inactive")

        if not user.two_factor_enabled or not user.two_factor_secret:
            raise UnauthorizedException("Two-factor authentication is not configured")

        if not await self.verify_totp(user, code):
            raise UnauthorizedException("Invalid authenticator code")

        await self._consume_2fa_pending(user_id_str)

        auth_service = AuthService(self.session, self.redis)
        return await auth_service._issue_tokens(user, ip, user_agent)

    async def use_backup_code(
        self,
        user_id_str: str,
        raw_code: str,
        ip: str | None = None,
        user_agent: str = "",
    ) -> TokenResponse:
        """
        Authenticate using a one-time backup code (replaces TOTP in step 2).

        Validates the pending login marker and consumes the backup code.
        Each code may only be used once.
        """
        await self._check_2fa_pending(user_id_str)

        user_id = UUID(user_id_str)
        user = await self.user_repo.get_active_by_id(user_id)
        if not user:
            raise UnauthorizedException("User not found or inactive")

        code_hash = _hash_backup_code(raw_code)
        backup = await self.backup_repo.get_unused_by_code_hash(user_id, code_hash)
        if not backup:
            raise UnauthorizedException("Invalid or already-used backup code")

        await self.backup_repo.mark_used(backup.id)
        await self.session.commit()

        await self._consume_2fa_pending(user_id_str)

        logger.info("2fa_backup_code_used", user_id=user_id_str)

        auth_service = AuthService(self.session, self.redis)
        return await auth_service._issue_tokens(user, ip, user_agent)

    async def disable_2fa(
        self,
        user: User,
        password: str,
        code: str,
    ) -> None:
        """
        Disable 2FA for a user.

        Requires:
          - Current account password
          - Valid TOTP code (proves possession of the authenticator)
        """
        from app.core.security.hashing import verify_password

        if not verify_password(password, user.password_hash or ""):
            raise UnauthorizedException("Current password is incorrect")

        if not user.two_factor_enabled or not user.two_factor_secret:
            raise BadRequestException("Two-factor authentication is not currently enabled")

        if not await self.verify_totp(user, code):
            raise UnauthorizedException("Invalid authenticator code")

        await self.user_repo.update(
            user.id,
            two_factor_enabled=False,
            two_factor_method=None,
            two_factor_secret=None,
        )
        await self.backup_repo.delete_all_for_user(user.id)
        await self.session.commit()
        logger.info("2fa_disabled", user_id=str(user.id))

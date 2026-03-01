"""
JWT creation and verification helpers.

AccessTokens are short-lived (15 min by default).
RefreshTokens are longer-lived (7 days) and stored in Redis for revocation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from jose import JWTError, jwt

from app.config import get_settings
from app.core.exceptions import UnauthorizedException
from app.shared.enums import TokenType


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(
    subject: str | UUID,
    org_id: str | UUID | None = None,
    extra_claims: dict[str, Any] | None = None,
    session_id: str | UUID | None = None,
) -> str:
    """Return a signed JWT access token."""
    settings = get_settings()
    expire = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": TokenType.ACCESS,
        "jti": str(uuid4()),
        "exp": expire,
        "iat": _now(),
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    if org_id is not None:
        payload["org_id"] = str(org_id)
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    subject: str | UUID,
    org_id: str | UUID | None = None,
) -> str:
    """Return a signed JWT refresh token."""
    settings = get_settings()
    expire = _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": TokenType.REFRESH,
        "jti": str(uuid4()),
        "exp": expire,
        "iat": _now(),
    }
    if org_id is not None:
        payload["org_id"] = str(org_id)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT.
    Raises UnauthorizedException on invalid / expired tokens.
    """
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise UnauthorizedException(f"Invalid or expired token: {exc}") from exc


def verify_token(token: str, expected_type: TokenType) -> dict[str, Any] | None:
    """Return decoded payload if token is valid and matches *expected_type*, else None."""
    try:
        payload = decode_token(token)
        if payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None

"""
Auth module FastAPI dependencies.

get_current_user         — require a valid access token; return the User
get_optional_current_user — same but return None instead of raising
require_verified_email   — additionally enforce email_verified == True
AuthDeps                 — dataclass bundling db + redis for service injection
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security.jwt import decode_token
from app.modules.auth.constants import DENYLIST_PREFIX
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.shared.enums import TokenType

# Registered OAuth2 scheme — tells OpenAPI where the login endpoint is
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=True,  # 401 if token is missing
)

oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,  # None if token is missing
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> User:
    """
    Decode the Bearer token, check the denylist, and return the active User.
    Raises UnauthorizedException on any failure.
    """
    # decode_token raises UnauthorizedException on invalid / expired tokens
    payload = decode_token(token)

    if payload.get("type") != TokenType.ACCESS:
        raise UnauthorizedException("Invalid token type")

    if await redis.get(f"{DENYLIST_PREFIX}{token}"):
        raise UnauthorizedException("Token has been revoked")

    user = await UserRepository(User, session).get_active_by_id(UUID(payload["sub"]))
    if not user:
        raise UnauthorizedException("User not found or inactive")

    return user


async def get_optional_current_user(
    token: str | None = Depends(oauth2_scheme_optional),
    session: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> User | None:
    """Like get_current_user but returns None instead of raising when unauthenticated."""
    if not token:
        return None
    try:
        return await get_current_user(token, session, redis)
    except UnauthorizedException:
        return None


async def require_verified_email(
    current_user: User = Depends(get_current_user),
) -> User:
    """Further require that the authenticated user has verified their email."""
    if not current_user.email_verified:
        raise ForbiddenException("Email address not verified. Please check your inbox.")
    return current_user


async def get_current_session_id(
    token: str = Depends(oauth2_scheme),
) -> Optional[UUID]:
    """
    Extract the session ID (`sid` claim) from the current access token.
    Returns None if the claim is absent (tokens issued before this feature).
    """
    try:
        payload = decode_token(token)
        sid = payload.get("sid")
        return UUID(sid) if sid else None
    except Exception:
        return None


# ── Bundled dependency ─────────────────────────────────────────────────────

@dataclass
class AuthDeps:
    """
    Bundles db + redis into a single dependency for AuthService construction.

    Usage::

        async def handler(deps: Annotated[AuthDeps, Depends()]) -> ...:
            service = AuthService(deps.db, deps.redis)
    """

    db: AsyncSession = Depends(get_db)
    redis: aioredis.Redis = Depends(get_redis)

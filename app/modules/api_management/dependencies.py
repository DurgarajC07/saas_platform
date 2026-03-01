"""
API Management FastAPI dependencies.

get_api_key_auth   — authenticate via X-API-Key or Bearer sk_... header
require_scope      — factory that returns a dependency enforcing a specific scope
ApiKeyDeps         — dataclass bundling db + redis for APIKeyService construction
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import redis.asyncio as aioredis
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.modules.api_management.models import APIKey
from app.modules.api_management.service import APIKeyService


# ── Primary authentication dependency ────────────────────────────────────────


async def get_api_key_auth(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> APIKey:
    """
    Extract the API key from either:
      - ``X-API-Key: sk_live_...`` header   (preferred for programmatic clients)
      - ``Authorization: Bearer sk_live_...``  header (for OAuth-style tooling)

    The key must start with ``sk_`` to be recognized as an API key (vs a JWT).
    Raises UnauthorizedException on any failure.
    """
    raw_key: str | None = x_api_key
    if raw_key is None and authorization:
        candidate = authorization.removeprefix("Bearer ").strip()
        if candidate.startswith("sk_"):
            raw_key = candidate

    if not raw_key or not raw_key.startswith("sk_"):
        raise UnauthorizedException("API key required (X-API-Key: sk_live_...)")

    client_ip: str | None = None
    if request.client:
        client_ip = request.client.host

    svc = APIKeyService(session, redis)
    return await svc.authenticate_api_key(raw_key, client_ip=client_ip)


# ── Scope enforcement ─────────────────────────────────────────────────────────


def require_scope(scope: str) -> Callable:
    """
    Dependency factory that validates the authenticated API key possesses the
    required scope.

    Usage::

        @router.get("/data")
        async def get_data(
            api_key: APIKey = Depends(require_scope("data:read"))
        ) -> ...:
            ...
    """
    async def _dep(api_key: APIKey = Depends(get_api_key_auth)) -> APIKey:
        # Empty scopes list means the key has full access
        if api_key.scopes and scope not in api_key.scopes:
            raise ForbiddenException(
                f"API key missing required scope: '{scope}'"
            )
        return api_key

    _dep.__name__ = f"require_scope_{scope.replace(':', '_')}"
    return _dep


# ── Bundled dependency dataclass ──────────────────────────────────────────────


@dataclass
class ApiKeyDeps:
    """
    Bundles db + redis into a single dependency for APIKeyService construction.

    Usage::

        async def handler(deps: Annotated[ApiKeyDeps, Depends()]) -> ...:
            svc = APIKeyService(deps.db, deps.redis)
    """

    db: AsyncSession = Depends(get_db)
    redis: aioredis.Redis = Depends(get_redis)

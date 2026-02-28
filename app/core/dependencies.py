"""
Shared FastAPI dependencies injected across route handlers.

get_db       - yields a per-request AsyncSession
get_redis    - returns the application Redis client
get_settings - re-exports config for use in Depends()
"""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.config import get_settings as _get_settings
from app.core.redis import get_redis as _get_redis


# -- Database -----------------------------------------------------------------
async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a transactional AsyncSession per HTTP request.
    Uses the session_factory stored on app.state by the lifespan handler.
    """
    async with request.app.state.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# -- Redis --------------------------------------------------------------------
async def get_redis() -> aioredis.Redis:
    """Return the application-wide Redis client."""
    return await _get_redis()


# -- Settings -----------------------------------------------------------------
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return _get_settings()

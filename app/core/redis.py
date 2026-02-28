"""
Async Redis client with lazy initialisation and health-check pings.

get_redis() returns the shared singleton; the lifespan handler calls
close_redis() on shutdown to cleanly drain the connection pool.
"""

import redis.asyncio as aioredis

from app.config import get_settings

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return the application-wide Redis client, creating it on first call."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            get_settings().REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection pool gracefully."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
"""
Redis caching utilities with typed helpers for hot data paths.

Design decisions
----------------
* All caching helpers accept an ``aioredis.Redis`` instance rather than
  calling ``get_redis()`` themselves — this keeps the layer testable (inject
  a fake client in tests) and avoids hidden global state.
* Data is JSON-serialised so it remains human-readable in redis-cli.
* TTLs are defined as module-level constants so they can be overridden from
  settings without touching every call site.
* Cache misses return ``None``; callers are responsible for population.

TTL constants (align with the performance guide)
-------------------------------------------------
PERMISSIONS_TTL      5 minutes  — per org-user permission set
FEATURE_FLAGS_TTL    5 minutes  — per-org feature-flag overrides
SYSTEM_SETTINGS_TTL  10 minutes — global platform config

Key schema (Redis namespace:sub-key)
-------------------------------------
permissions:{org_user_id}
feature_flags:{org_id}
system_settings           (single key — no sub-key)
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
import redis.asyncio as aioredis

logger = structlog.get_logger(__name__)

# ── TTL constants ─────────────────────────────────────────────────────────────

PERMISSIONS_TTL: int = 5 * 60       # 300 seconds
FEATURE_FLAGS_TTL: int = 5 * 60     # 300 seconds
SYSTEM_SETTINGS_TTL: int = 10 * 60  # 600 seconds

# ── Key builders ──────────────────────────────────────────────────────────────

def _permissions_key(org_user_id: UUID | str) -> str:
    return f"permissions:{org_user_id}"


def _feature_flags_key(org_id: UUID | str) -> str:
    return f"feature_flags:{org_id}"


_SYSTEM_SETTINGS_KEY = "system_settings"


# ── Generic low-level helpers ─────────────────────────────────────────────────

async def cache_get(redis: aioredis.Redis, key: str) -> Any | None:
    """
    Fetch a JSON-serialised value from Redis.

    Returns the deserialised Python object, or ``None`` on a cache miss.
    Logs (but does not raise) on Redis errors so a cache failure never
    crashes the request.
    """
    try:
        raw = await redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        await logger.awarning("cache.get_error", key=key, error=str(exc))
        return None


async def cache_set(
    redis: aioredis.Redis,
    key: str,
    value: Any,
    ttl: int,
) -> None:
    """
    Serialise *value* to JSON and store it with the given TTL (seconds).

    Silently absorbs Redis errors to maintain the "cache as enhancement"
    contract — the application must never *depend* on the cache being written.
    """
    try:
        await redis.setex(key, ttl, json.dumps(value))
    except Exception as exc:
        await logger.awarning("cache.set_error", key=key, error=str(exc))


async def cache_delete(redis: aioredis.Redis, key: str) -> None:
    """Remove a single cache entry (use on mutation paths to bust stale data)."""
    try:
        await redis.delete(key)
    except Exception as exc:
        await logger.awarning("cache.delete_error", key=key, error=str(exc))


async def cache_delete_pattern(redis: aioredis.Redis, pattern: str) -> int:
    """
    Delete all keys matching *pattern* (e.g. ``"feature_flags:*"``).

    Uses SCAN + DEL to avoid blocking the Redis server with KEYS.
    Returns the number of keys deleted.
    """
    deleted = 0
    try:
        async for key in redis.scan_iter(match=pattern, count=100):
            await redis.delete(key)
            deleted += 1
    except Exception as exc:
        await logger.awarning("cache.delete_pattern_error", pattern=pattern, error=str(exc))
    return deleted


# ── Domain-specific helpers ───────────────────────────────────────────────────

async def get_cached_permissions(
    redis: aioredis.Redis,
    org_user_id: UUID | str,
) -> list[str] | None:
    """
    Return the cached permission-name list for an org membership, or ``None``.

    Expected value shape: ``["project.create", "billing.read", …]``
    """
    return await cache_get(redis, _permissions_key(org_user_id))


async def set_cached_permissions(
    redis: aioredis.Redis,
    org_user_id: UUID | str,
    permissions: list[str],
) -> None:
    """Cache the permission list for *org_user_id* for PERMISSIONS_TTL seconds."""
    await cache_set(redis, _permissions_key(org_user_id), permissions, PERMISSIONS_TTL)


async def invalidate_permissions(
    redis: aioredis.Redis,
    org_user_id: UUID | str,
) -> None:
    """Bust the permission cache for a specific org-user (e.g. after role change)."""
    await cache_delete(redis, _permissions_key(org_user_id))


async def invalidate_all_permissions_for_org(
    redis: aioredis.Redis,
    org_id: UUID | str,
) -> int:
    """
    Bust *all* permission cache entries whose key contains the org UUID.

    Useful when an org-level role or plan changes affects many members.
    Note: this performs a SCAN and may be slow for very large orgs.
    """
    return await cache_delete_pattern(redis, f"permissions:*{org_id}*")


async def get_cached_feature_flags(
    redis: aioredis.Redis,
    org_id: UUID | str,
) -> dict[str, Any] | None:
    """
    Return the cached feature-flag map for *org_id*, or ``None``.

    Expected value shape::

        {
            "sso": True,
            "api_access": True,
            "advanced_analytics": False,
            "max_seats": 50,
        }
    """
    return await cache_get(redis, _feature_flags_key(org_id))


async def set_cached_feature_flags(
    redis: aioredis.Redis,
    org_id: UUID | str,
    flags: dict[str, Any],
) -> None:
    """Cache the feature-flag map for *org_id* for FEATURE_FLAGS_TTL seconds."""
    await cache_set(redis, _feature_flags_key(org_id), flags, FEATURE_FLAGS_TTL)


async def invalidate_feature_flags(
    redis: aioredis.Redis,
    org_id: UUID | str,
) -> None:
    """Bust the feature-flag cache for a specific org (e.g. after plan change)."""
    await cache_delete(redis, _feature_flags_key(org_id))


async def get_cached_system_settings(
    redis: aioredis.Redis,
) -> dict[str, Any] | None:
    """
    Return the cached global system-settings dict, or ``None``.

    Expected value shape: ``{"maintenance_mode": false, "default_plan_id": "…"}``
    """
    return await cache_get(redis, _SYSTEM_SETTINGS_KEY)


async def set_cached_system_settings(
    redis: aioredis.Redis,
    settings: dict[str, Any],
) -> None:
    """Cache the global system-settings map for SYSTEM_SETTINGS_TTL seconds."""
    await cache_set(redis, _SYSTEM_SETTINGS_KEY, settings, SYSTEM_SETTINGS_TTL)


async def invalidate_system_settings(redis: aioredis.Redis) -> None:
    """Bust the system-settings cache (e.g. after an admin updates a setting)."""
    await cache_delete(redis, _SYSTEM_SETTINGS_KEY)

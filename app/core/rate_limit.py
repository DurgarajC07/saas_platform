"""
Rate limiting utilities — Redis fixed-window counter strategy.

Why a custom implementation?
------------------------------
fastapi-limiter 0.2.x switched from a Redis-backed API to pyrate-limiter and
no longer ships a ``FastAPILimiter.init()`` bootstrap API.  Rather than fight
the library's churn, we own a minimal Redis-native implementation:

  • All state lives in Redis  →  works across multiple gunicorn workers / pods.
  • Simple, auditable, no external Lua dependencies.
  • Keys use a human-readable schema for easy inspection via redis-cli.

Algorithm
---------
Fixed-window counter: ``INCR key`` then ``EXPIRE key seconds`` (only on the
first increment so subsequent requests don't reset the window).  Atomic enough
for all practical rate-limiting purposes.

Key schema
----------
``rl:{endpoint_slug}:{client_ip}``        →  int (request count in window)

Usage
-----
Declare a limiter constant::

    LoginRateLimit = rate_limit(times=5, seconds=300)

Apply as a FastAPI dependency::

    @router.post("/login", dependencies=[Depends(LoginRateLimit)])
    async def login(...): ...

The limiter reads the Redis client from ``request.app.state.redis`` so it
requires no separate initialisation step — it piggybacks on the lifespan.

Pre-configured limiters
-----------------------
LoginRateLimit         5 req / 5 min    brute-force protection
RegisterRateLimit      3 req / 1 hour   account-farm protection
ForgotPasswordLimit    3 req / 1 hour   prevents email flooding
RefreshTokenLimit      20 req / 1 min   excessive token rotation guard
ApiKeyVerifyLimit      30 req / 1 min   per-IP key validation
"""

from __future__ import annotations

from typing import Callable

import structlog
from fastapi import HTTPException, Request, status

logger = structlog.get_logger(__name__)


def _get_client_ip(request: Request) -> str:
    """
    Extract the real client IP.

    Honours ``X-Forwarded-For`` set by reverse proxies (nginx, AWS ALB, etc.)
    and falls back to the direct TCP connection address.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _endpoint_slug(request: Request) -> str:
    """
    Derive a short, stable key component from the request path and method.

    Example: ``POST /api/v1/auth/login``  →  ``post_api_v1_auth_login``
    """
    return f"{request.method}_{request.url.path}".lower().replace("/", "_").strip("_")


def rate_limit(times: int, seconds: int) -> Callable:
    """
    Return a FastAPI Depends-compatible callable that enforces a rate limit.

    Parameters
    ----------
    times:
        Maximum number of allowed requests within the window.
    seconds:
        Length of the rate-limit window in seconds.

    Raises
    ------
    HTTP 429 Too Many Requests — includes ``Retry-After`` header.
    """

    async def _check(request: Request) -> None:
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            # No Redis → fail open (never block in degraded mode)
            return

        ip = _get_client_ip(request)
        slug = _endpoint_slug(request)
        key = f"rl:{slug}:{ip}"

        try:
            count = await redis.incr(key)
            if count == 1:
                # First hit in a fresh window — set the TTL
                await redis.expire(key, seconds)

            if count > times:
                ttl = await redis.ttl(key)
                retry_after = str(max(ttl, 1))
                await logger.awarning(
                    "rate_limit.exceeded",
                    key=key,
                    count=count,
                    limit=times,
                    window=seconds,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "code": "RATE_LIMITED",
                        "message": "Too many requests. Please try again later.",
                        "retry_after": int(retry_after),
                    },
                    headers={"Retry-After": retry_after},
                )
        except HTTPException:
            raise
        except Exception as exc:
            # Redis error → fail open so a cache outage never locks out users
            await logger.awarning("rate_limit.redis_error", key=key, error=str(exc))

    return _check


# ── Pre-configured limiters ───────────────────────────────────────────────────
# Import and apply these directly in router files:
#
#   from app.core.rate_limit import LoginRateLimit
#   @router.post("/login", dependencies=[Depends(LoginRateLimit)])

#: 5 attempts per 5 minutes — protects against brute-force credential attacks.
LoginRateLimit = rate_limit(times=5, seconds=300)

#: 3 registrations per hour per IP — slows down account-farm automation.
RegisterRateLimit = rate_limit(times=3, seconds=3600)

#: 3 forgot-password requests per hour — prevents mailbox flooding.
ForgotPasswordLimit = rate_limit(times=3, seconds=3600)

#: 20 token refreshes per minute — guards against excessive rotation.
RefreshTokenLimit = rate_limit(times=20, seconds=60)

#: 30 API-key validations per minute per IP.
ApiKeyVerifyLimit = rate_limit(times=30, seconds=60)

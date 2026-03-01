"""
IP Block Middleware.

Checks the incoming request IP against the Redis block-list.
Blocked IPs receive an immediate 403 — no further processing occurs.

Redis key format: ``blocked_ip:{ip_address}``
The key is populated by SecurityService.block_ip() / _auto_block_ip()
and removed by SecurityService.unblock_ip().
"""

from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)

_BLOCKED_IP_PREFIX = "blocked_ip:"


class IPBlockMiddleware(BaseHTTPMiddleware):
    """Reject requests from IPs present in the Redis block-list."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return await call_next(request)

        ip = request.client.host if request.client else None
        if ip:
            blocked = await redis.get(f"{_BLOCKED_IP_PREFIX}{ip}")
            if blocked:
                logger.warning(
                    "ip_block.rejected",
                    ip=ip,
                    path=request.url.path,
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Access denied", "code": "IP_BLOCKED"},
                )

        return await call_next(request)

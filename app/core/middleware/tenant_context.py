"""
TenantContextMiddleware — third in the middleware chain.

Parses the Bearer JWT from the Authorization header, extracts
``organization_id``, and stores it in ``request.state.org_id``.

The repository layer reads ``request.state.org_id`` for automatic
row-level scoping — no manuel filtering required per query.

Routes that do not require a tenant (auth endpoints, public routes)
are not blocked; org_id is simply left as ``None``.
"""

from uuid import UUID

import structlog
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

logger = structlog.get_logger(__name__)

# Paths that intentionally have no tenant context
_PUBLIC_PREFIXES = (
    "/api/v1/auth/",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/health",
    "/metrics",
)


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        request.state.org_id = None

        path = request.url.path
        if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
            return await call_next(request)

        # 1. Explicit header takes priority — allows multi-org users to switch context
        header_org_id = request.headers.get("X-Organization-ID")
        if header_org_id:
            try:
                request.state.org_id = UUID(header_org_id)
                structlog.contextvars.bind_contextvars(org_id=header_org_id)
                return await call_next(request)
            except ValueError:
                logger.warning("Invalid X-Organization-ID header value", value=header_org_id)

        # 2. Fall back to org_id embedded in the JWT payload
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ")
            settings = get_settings()
            try:
                payload = jwt.decode(
                    token,
                    settings.JWT_SECRET_KEY,
                    algorithms=[settings.JWT_ALGORITHM],
                )
                org_id_raw = payload.get("org_id")
                if org_id_raw:
                    request.state.org_id = UUID(str(org_id_raw))
                    structlog.contextvars.bind_contextvars(org_id=str(request.state.org_id))
            except (JWTError, ValueError):
                # Invalid token — let the route handler return 401
                pass

        return await call_next(request)

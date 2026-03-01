"""
SecurityHeadersMiddleware — injects OWASP-recommended HTTP security headers.

Headers added to every response
--------------------------------
X-Content-Type-Options: nosniff
    Prevents MIME-type sniffing — stops browsers from treating plain text
    as executable JS.

X-Frame-Options: DENY
    Blocks this page from being embedded in a <frame> or <iframe> to prevent
    clickjacking attacks.

X-XSS-Protection: 0
    Disables the legacy browser XSS auditor (it causes more harm than good in
    modern browsers; CSP is the correct mitigation).

Referrer-Policy: strict-origin-when-cross-origin
    Sends the full URL as referrer for same-origin requests; only the origin
    for cross-origin HTTPS→HTTPS; nothing for HTTPS→HTTP downgrade.

Permissions-Policy: camera=(), microphone=(), geolocation=()
    Explicitly disables powerful browser features that this API never needs.

Strict-Transport-Security (HSTS)
    Added **only in production** (ENVIRONMENT=production) because localhost
    HTTPS is almost never set up in development.
    max-age=31536000; includeSubDomains; preload
"""

from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)

_STATIC_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
}

_HSTS_VALUE = "max-age=31536000; includeSubDomains; preload"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Attach security-hardening response headers to every HTTP response.

    HSTS is conditionally appended only when ``is_production=True`` so that
    local development with plain HTTP does not accidentally trigger browser-level
    strict-transport enforcement.
    """

    def __init__(self, app: ASGIApp, is_production: bool = False) -> None:
        super().__init__(app)
        self._is_production = is_production

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)

        for header, value in _STATIC_HEADERS.items():
            response.headers[header] = value

        if self._is_production:
            response.headers["Strict-Transport-Security"] = _HSTS_VALUE

        return response

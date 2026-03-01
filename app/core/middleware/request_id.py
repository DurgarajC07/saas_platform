"""
RequestIDMiddleware — outermost middleware in the chain.

Attaches a unique X-Request-ID to every request and response.
If the client supplies one, it is reused (useful for distributed tracing).
The ID is also stored in structlog's context so it appears in every log line
emitted during that request.
"""

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        request_id = request.headers.get(self.header_name) or str(uuid.uuid4())
        request.state.request_id = request_id

        # Bind to structlog context so all log lines carry the request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers[self.header_name] = request_id
        return response

"""
Prometheus metrics middleware + collector.

Instruments every HTTP request with:
  • http_requests_total          – Counter  (method, path_template, status_code)
  • http_request_duration_seconds – Histogram (method, path_template)

The ``/metrics`` endpoint is exposed as a plain FastAPI route on the system
router (admin-only) rather than as a standalone ASGI app so that it benefits
from the existing auth middleware chain.
"""

from __future__ import annotations

import time
from typing import Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

# ── Metric definitions ────────────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path_template", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path_template"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)


def _path_template(request: Request) -> str:
    """
    Return the matched route template (e.g. ``/api/v1/users/{user_id}``) instead
    of the concrete URL so that per-user cardinality does not explode label sets.
    Falls back to the raw path when no route matched.
    """
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    return request.url.path


# ── Middleware ────────────────────────────────────────────────────────────────


class PrometheusMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that records request count and latency for every request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        path = _path_template(request)
        method = request.method
        status = str(response.status_code)

        REQUEST_COUNT.labels(method=method, path_template=path, status_code=status).inc()
        REQUEST_LATENCY.labels(method=method, path_template=path).observe(duration)

        return response


# ── Metrics text endpoint helper ──────────────────────────────────────────────


def metrics_response() -> Response:
    """
    Return a Prometheus text-format ``Response`` containing all registered metrics.
    Call this from the ``GET /metrics`` route handler.
    """
    data = generate_latest()
    return Response(
        content=data,
        media_type=CONTENT_TYPE_LATEST,
    )

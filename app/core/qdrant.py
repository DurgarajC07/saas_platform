"""
Qdrant async-client singleton.

Usage:
    from app.core.qdrant import get_qdrant_client

    client = get_qdrant_client()
    await client.get_collections()

The client is instantiated once per process (via lru_cache) and reused
across requests.  It does NOT maintain a persistent connection pool —
AsyncQdrantClient opens a fresh HTTPX session per request by default,
which is fine for the expected call volume.

For Docker Compose deployments the QDRANT_URL should be set to
http://qdrant:6333 via environment variable.
"""

from __future__ import annotations

from functools import lru_cache

import structlog
from qdrant_client import AsyncQdrantClient

from app.config import get_settings

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_qdrant_client() -> AsyncQdrantClient:
    """Return the shared AsyncQdrantClient singleton."""
    settings = get_settings()
    api_key = settings.QDRANT_API_KEY or None  # empty string → None
    client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=api_key,
    )
    log.info("qdrant.client_created", url=settings.QDRANT_URL)
    return client

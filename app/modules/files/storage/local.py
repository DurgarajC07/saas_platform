"""
Local filesystem storage adapter.

Stores files under ``LOCAL_STORAGE_PATH`` (default: /tmp/uploads).
download() reads bytes directly; generate_presigned_url() returns a
relative API path that the router handles via a streaming response.

This adapter is intended for development / single-server deployments
only.  In production use S3 or another distributed backend.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles
import structlog

from app.config import Settings
from app.modules.files.storage.base import StorageBase

log = structlog.get_logger(__name__)


class LocalStorage(StorageBase):
    """Filesystem-based storage backend."""

    def __init__(self, settings: Settings) -> None:
        self.base_path = Path(settings.LOCAL_STORAGE_PATH)
        self.base_path.mkdir(parents=True, exist_ok=True)
        log.info("local_storage.init", base_path=str(self.base_path))

    def _full_path(self, path: str) -> Path:
        # Resolve the path relative to the base directory but prevent traversal
        resolved = (self.base_path / path).resolve()
        if not str(resolved).startswith(str(self.base_path.resolve())):
            raise ValueError(f"Path traversal attempt detected: {path}")
        return resolved

    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        full = self._full_path(path)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: full.parent.mkdir(parents=True, exist_ok=True))
        async with aiofiles.open(full, "wb") as fh:
            await fh.write(data)
        log.debug("local.upload", path=path, bytes=len(data))
        return path

    async def download(self, path: str) -> bytes:
        full = self._full_path(path)
        async with aiofiles.open(full, "rb") as fh:
            data = await fh.read()
        log.debug("local.download", path=path, bytes=len(data))
        return data

    async def delete(self, path: str) -> None:
        full = self._full_path(path)
        if full.exists():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, full.unlink)
            log.debug("local.delete", path=path)

    async def generate_presigned_url(self, path: str, expires: int = 3600) -> str:
        # Local storage: return an internal API endpoint URL
        # The router proxies this through GET /files/local-stream/{path}
        return f"/api/v1/files/local-stream/{path}"

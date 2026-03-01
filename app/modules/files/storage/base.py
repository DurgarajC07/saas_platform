"""
Abstract storage adapter interface.

All concrete storage backends (S3, GCS, Azure, Local) must implement
this interface.  The service layer depends only on StorageBase, so
providers can be swapped transparently via config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageBase(ABC):
    """Strategy interface for object storage operations."""

    @abstractmethod
    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        """
        Upload *data* to *path* and return the canonical storage path.

        The returned path is stored in the DB and passed back to other
        methods (download / delete / presigned_url).
        """
        ...

    @abstractmethod
    async def download(self, path: str) -> bytes:
        """Return the raw bytes of the object at *path*."""
        ...

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Permanently remove the object at *path*."""
        ...

    @abstractmethod
    async def generate_presigned_url(self, path: str, expires: int = 3600) -> str:
        """
        Return a time-limited URL that allows direct access to the object.

        For S3 / GCS this is a proper signed URL; for local storage it
        returns a download endpoint URL.
        """
        ...

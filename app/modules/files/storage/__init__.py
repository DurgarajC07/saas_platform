"""
Storage adapter factory.

Resolves the active StorageBase implementation from STORAGE_PROVIDER
config at application startup.  The resolved instance is cached and
reused for the lifetime of the process.
"""

from __future__ import annotations

from app.modules.files.storage.base import StorageBase

_storage_instance: StorageBase | None = None


def get_storage(settings=None) -> StorageBase:
    """
    Return the singleton storage adapter for the current configuration.

    The instance is created once and cached for the process lifetime.
    Pass ``settings`` explicitly for testing; in production the app
    settings are resolved automatically via ``get_settings()``.

    Supported providers:
        - ``s3``    → S3Storage (aioboto3)
        - ``local`` → LocalStorage (aiofiles, for dev/test)
    """
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    if settings is None:
        from app.config import get_settings
        settings = get_settings()

    provider = (settings.STORAGE_PROVIDER or "local").lower()
    if provider == "s3":
        from app.modules.files.storage.s3 import S3Storage
        _storage_instance = S3Storage(settings)
    else:
        from app.modules.files.storage.local import LocalStorage
        _storage_instance = LocalStorage(settings)

    return _storage_instance


__all__ = ["StorageBase", "get_storage"]

"""
Celery task: async storage cleanup.

Called after a soft-delete so that the HTTP response returns quickly.
The task deletes the physical object from the backing storage provider,
retrying up to 3 times with exponential backoff on transient errors.
"""

from __future__ import annotations

import asyncio
import structlog

from app.core.celery_app import celery_app

log = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.files.cleanup_storage_object",
    max_retries=3,
    default_retry_delay=30,
    queue="default",
    acks_late=True,
)
def cleanup_storage_object(
    self,
    storage_path: str,
    storage_provider: str,
) -> dict:
    """
    Delete a physical storage object after a file record is soft-deleted.

    Args:
        storage_path:     The canonical path returned by StorageBase.upload().
        storage_provider: The provider string stored in the DB row («s3» | «local»).
    """
    try:
        return asyncio.run(
            _delete_async(storage_path=storage_path, storage_provider=storage_provider)
        )
    except Exception as exc:
        retry_count = self.request.retries
        countdown = 30 * (2 ** retry_count)
        log.warning(
            "storage_cleanup.retry",
            path=storage_path,
            provider=storage_provider,
            attempt=retry_count + 1,
            countdown=countdown,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _delete_async(*, storage_path: str, storage_provider: str) -> dict:
    """Coroutine that performs the actual delete against the storage layer."""
    from app.modules.files.storage import get_storage

    storage = get_storage()

    await storage.delete(storage_path)
    log.info(
        "storage_cleanup.success",
        path=storage_path,
        provider=storage_provider,
    )
    return {"deleted": True, "path": storage_path}

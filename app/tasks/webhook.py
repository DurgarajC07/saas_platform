"""
Celery tasks — webhook delivery.

deliver_webhook(delivery_id)
  • Signs the payload with HMAC-SHA256.
  • POSTs to the webhook URL with a 30-second timeout.
  • Records response status and body on the delivery row.
  • Retries with exponential backoff: 1, 2, 4, 8, 16 minutes.
  • After 5 consecutive failures, auto-deactivates the webhook and notifies.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, UTC
from uuid import UUID

import httpx
import structlog

from app.core.celery_app import celery_app
from app.config import get_settings

logger = structlog.get_logger(__name__)

_MAX_FAILURES = 5


# ── Async implementation ─────────────────────────────────────────────────────


async def _deliver_async(delivery_id: UUID, retry_count: int) -> tuple[bool, str | None]:
    """
    Core delivery logic executed inside an asyncio event loop by the Celery task.

    Returns (success: bool, error_message: str | None).
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from app.modules.api_management.models import WebhookDelivery, Webhook
    from app.modules.api_management.repository import WebhookDeliveryRepository, WebhookRepository
    from app.core.security.encryption import safe_decrypt

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=2)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as session:
            delivery_repo = WebhookDeliveryRepository(session)
            webhook_repo = WebhookRepository(session)

            delivery = await delivery_repo.get_by_id(delivery_id)
            if delivery is None:
                logger.error("webhook.delivery.not_found", delivery_id=str(delivery_id))
                return False, "Delivery record not found"

            webhook = await webhook_repo.get_by_id(delivery.webhook_id)
            if webhook is None:
                logger.error("webhook.not_found", webhook_id=str(delivery.webhook_id))
                await delivery_repo.update(delivery_id, status="failed", attempts=delivery.attempts + 1)
                await session.commit()
                return False, "Webhook not found"

            if not webhook.is_active:
                await delivery_repo.update(delivery_id, status="failed", attempts=delivery.attempts + 1)
                await session.commit()
                return False, "Webhook is inactive"

            # ── Build and sign payload ───────────────────────────────────
            payload_str = json.dumps(delivery.payload, default=str)
            raw_secret = safe_decrypt(webhook.secret)
            sig = hmac.new(
                raw_secret.encode(),
                payload_str.encode(),
                hashlib.sha256,
            ).hexdigest()

            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Signature": f"sha256={sig}",
                "X-Webhook-Event": delivery.event,
                "X-Webhook-Delivery-Id": str(delivery_id),
            }

            # ── Make HTTP request ────────────────────────────────────────
            start_ms = int(time.time() * 1000)
            success = False
            error_msg: str | None = None
            response_status: int | None = None
            response_body: str | None = None

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(str(webhook.url), content=payload_str, headers=headers)
                response_status = resp.status_code
                response_body = resp.text[:2000]  # cap stored body
                response_time_ms = int(time.time() * 1000) - start_ms
                success = resp.is_success
                if not success:
                    error_msg = f"HTTP {resp.status_code}"
            except Exception as exc:
                response_time_ms = int(time.time() * 1000) - start_ms
                error_msg = str(exc)[:500]
                logger.warning("webhook.delivery.http_error", error=error_msg, delivery_id=str(delivery_id))

            # ── Persist attempt result ───────────────────────────────────
            new_attempts = delivery.attempts + 1
            if success:
                await delivery_repo.update(
                    delivery_id,
                    status="delivered",
                    attempts=new_attempts,
                    response_status=response_status,
                    response_body=response_body,
                    response_time_ms=response_time_ms,
                    next_retry_at=None,
                )
                await webhook_repo.reset_failure_count(webhook.id)
                logger.info(
                    "webhook.delivery.success",
                    delivery_id=str(delivery_id),
                    webhook_id=str(webhook.id),
                    status=response_status,
                )
            else:
                await delivery_repo.update(
                    delivery_id,
                    status="failed",
                    attempts=new_attempts,
                    response_status=response_status,
                    response_body=response_body,
                    response_time_ms=response_time_ms if "response_time_ms" in dir() else None,
                )
                # Only increment failure counter on the *first* attempt and
                # on each subsequent attempt that fails.
                updated_hook = await webhook_repo.increment_failure(
                    webhook.id,
                    error_msg or "Unknown error",
                    auto_deactivate_threshold=_MAX_FAILURES,
                )
                if updated_hook and not updated_hook.is_active:
                    logger.warning(
                        "webhook.auto_deactivated",
                        webhook_id=str(webhook.id),
                        failure_count=updated_hook.failure_count,
                    )

            await session.commit()
            return success, error_msg
    finally:
        await engine.dispose()


# ── Celery task ──────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=_MAX_FAILURES - 1, name="app.tasks.webhook.deliver_webhook")
def deliver_webhook(self, delivery_id: str) -> dict:
    """
    Deliver a single webhook payload identified by its delivery_id (UUID str).

    On HTTP/network failure, retries up to 4 more times with exponential backoff:
      attempt 1 → wait  1 min
      attempt 2 → wait  2 min
      attempt 3 → wait  4 min
      attempt 4 → wait  8 min
      attempt 5 → wait 16 min (then gives up)
    """
    uid = UUID(delivery_id)
    retry_count = self.request.retries

    success, error_msg = asyncio.run(_deliver_async(uid, retry_count))

    if not success and retry_count < self.max_retries:
        delay_seconds = 60 * (2 ** retry_count)  # 60, 120, 240, 480, 960 s
        logger.info(
            "webhook.delivery.retry_scheduled",
            delivery_id=delivery_id,
            attempt=retry_count + 1,
            delay_s=delay_seconds,
        )

        # Update next_retry_at on the delivery record asynchronously
        async def _set_retry_at() -> None:
            from datetime import timedelta
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
            from app.modules.api_management.repository import WebhookDeliveryRepository
            settings = get_settings()
            engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=2)
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as session:
                    repo = WebhookDeliveryRepository(session)
                    next_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
                    await repo.update(uid, next_retry_at=next_at, status="pending")
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(_set_retry_at())
        raise self.retry(countdown=delay_seconds, exc=Exception(error_msg or "delivery failed"))

    return {"delivery_id": delivery_id, "success": success}

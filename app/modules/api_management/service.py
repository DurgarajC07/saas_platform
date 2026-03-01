"""
API Management service layer.

APIKeyService
  • create_api_key  — generate raw key, hash it, store prefix only
  • authenticate_api_key — SHA-256 lookup + expiry + rate limiting
  • check_rate_limit — Redis sliding-window per key per minute
  • list_keys        — paginated org keys (no secrets)
  • revoke_key       — mark key inactive + revoked_at timestamp

WebhookService
  • create_webhook   — random signing secret (encrypted at rest)
  • list_webhooks    — paginated org webhooks
  • get_webhook      — single webhook with org ownership check
  • update_webhook   — update url / events / is_active
  • delete_webhook   — soft delete
  • dispatch_event   — create WebhookDelivery records + enqueue Celery tasks
  • list_deliveries  — paginated delivery history for a webhook
"""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from datetime import datetime, UTC
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    RateLimitException,
    UnauthorizedException,
)
from app.core.security.encryption import encrypt
from app.core.pagination import paginate
from app.modules.api_management.models import APIKey
from app.modules.api_management.repository import (
    APIKeyRepository,
    WebhookDeliveryRepository,
    WebhookRepository,
)
from app.modules.api_management.schemas import (
    APIKeyListResponse,
    APIKeyResponse,
    CreateKeyRequest,
    CreateKeyResponse,
    CreateWebhookRequest,
    CreateWebhookResponse,
    UpdateWebhookRequest,
    WebhookDeliveryListResponse,
    WebhookDeliveryResponse,
    WebhookListResponse,
    WebhookResponse,
)
from app.modules.auth.models import User
from app.shared.base_schemas import PaginationMeta

logger = structlog.get_logger(__name__)

_RATE_LIMIT_WINDOW_SECONDS = 120  # keep 2-min window so previous-minute counts don't vanish


# ── APIKeyService ────────────────────────────────────────────────────────────


class APIKeyService:
    def __init__(self, session: AsyncSession, redis: aioredis.Redis | None = None) -> None:
        self.session = session
        self.redis = redis
        self.key_repo = APIKeyRepository(session)

    # ── Create ─────────────────────────────────────────────────────────

    async def create_api_key(
        self,
        org_id: UUID,
        creator: User,
        data: CreateKeyRequest,
    ) -> CreateKeyResponse:
        """
        Generate a new API key for the organisation.
        The full raw key is returned once; only the hash and prefix are stored.
        """
        raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:10]

        api_key = await self.key_repo.create(
            organization_id=org_id,
            created_by=creator.id,
            name=data.name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=data.scopes,
            rate_limit_per_minute=data.rate_limit_per_minute,
            expires_at=data.expires_at,
        )

        logger.info(
            "api_key.created",
            org_id=str(org_id),
            key_id=str(api_key.id),
            prefix=key_prefix,
        )

        return CreateKeyResponse(
            id=api_key.id,
            key=raw_key,
            prefix=key_prefix,
            name=api_key.name,
            scopes=api_key.scopes,
            rate_limit_per_minute=api_key.rate_limit_per_minute,
            expires_at=api_key.expires_at,
            created_at=api_key.created_at,
        )

    # ── Authenticate ───────────────────────────────────────────────────

    async def authenticate_api_key(
        self,
        raw_key: str,
        client_ip: str | None = None,
    ) -> APIKey:
        """
        Validate the raw key: lookup by SHA-256 hash, check active / expiry,
        enforce per-key rate limit, update last_used metadata.
        """
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key = await self.key_repo.get_by_hash(key_hash)

        if not api_key:
            raise UnauthorizedException("Invalid API key")
        if not api_key.is_active or api_key.revoked_at is not None:
            raise UnauthorizedException("API key has been revoked")
        if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
            raise UnauthorizedException("API key has expired")

        # ── Rate limiting ──────────────────────────────────────────────
        if self.redis is not None:
            await self._check_rate_limit(api_key)

        # ── Update last-used ───────────────────────────────────────────
        await self.key_repo.update_last_used(api_key.id, ip=client_ip)

        # Refresh after bulk UPDATE so all columns (incl. updated_at) are loaded
        # without requiring a lazy async IO outside of greenlet context.
        await self.session.refresh(api_key)

        return api_key

    async def _check_rate_limit(self, api_key: APIKey) -> None:
        """Sliding-window rate limit using Redis INCR + EXPIRE."""
        minute_bucket = int(time.time() // 60)
        redis_key = f"rate:apikey:{api_key.id}:{minute_bucket}"
        count = await self.redis.incr(redis_key)
        if count == 1:
            await self.redis.expire(redis_key, _RATE_LIMIT_WINDOW_SECONDS)
        if count > api_key.rate_limit_per_minute:
            raise RateLimitException(
                f"API key rate limit exceeded ({api_key.rate_limit_per_minute} req/min)"
            )

    # ── List / Revoke ──────────────────────────────────────────────────

    async def list_keys(
        self,
        org_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        include_revoked: bool = False,
    ) -> APIKeyListResponse:
        limit = page_size
        offset = (page - 1) * page_size
        rows, total = await self.key_repo.list_by_org(
            org_id,
            include_revoked=include_revoked,
            limit=limit,
            offset=offset,
        )
        total_pages = math.ceil(total / page_size) if page_size else 1
        return APIKeyListResponse(
            keys=[APIKeyResponse.model_validate(r) for r in rows],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            ),
        )

    async def revoke_key(self, key_id: UUID, org_id: UUID) -> APIKeyResponse:
        api_key = await self.key_repo.get_by_id(key_id)
        if not api_key:
            raise NotFoundException("API key not found")
        if api_key.organization_id != org_id:
            raise ForbiddenException("API key does not belong to your organisation")
        if api_key.revoked_at:
            raise ConflictException("API key is already revoked")

        updated = await self.key_repo.revoke(key_id)
        logger.info("api_key.revoked", key_id=str(key_id), org_id=str(org_id))
        return APIKeyResponse.model_validate(updated)


# ── WebhookService ────────────────────────────────────────────────────────────


class WebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.hook_repo = WebhookRepository(session)
        self.delivery_repo = WebhookDeliveryRepository(session)

    # ── Create ─────────────────────────────────────────────────────────

    async def create_webhook(
        self,
        org_id: UUID,
        creator: User,
        data: CreateWebhookRequest,
    ) -> CreateWebhookResponse:
        raw_secret = secrets.token_urlsafe(32)
        encrypted_secret = encrypt(raw_secret)

        hook = await self.hook_repo.create(
            organization_id=org_id,
            created_by=creator.id,
            url=str(data.url),
            secret=encrypted_secret,
            events=data.events,
        )

        logger.info(
            "webhook.created",
            org_id=str(org_id),
            webhook_id=str(hook.id),
            url=str(data.url),
        )

        return CreateWebhookResponse(
            id=hook.id,
            organization_id=hook.organization_id,
            created_by=hook.created_by,
            url=hook.url,
            events=hook.events,
            is_active=hook.is_active,
            failure_count=hook.failure_count,
            last_failure_reason=hook.last_failure_reason,
            last_triggered_at=hook.last_triggered_at,
            created_at=hook.created_at,
            updated_at=hook.updated_at,
            signing_secret=raw_secret,
        )

    # ── Read ───────────────────────────────────────────────────────────

    async def list_webhooks(
        self,
        org_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> WebhookListResponse:
        limit = page_size
        offset = (page - 1) * page_size
        rows, total = await self.hook_repo.list_by_org(org_id, limit=limit, offset=offset)
        total_pages = math.ceil(total / page_size) if page_size else 1
        return WebhookListResponse(
            webhooks=[WebhookResponse.model_validate(h) for h in rows],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            ),
        )

    async def get_webhook(self, webhook_id: UUID, org_id: UUID) -> WebhookResponse:
        hook = await self.hook_repo.get_by_id(webhook_id)
        if not hook:
            raise NotFoundException("Webhook not found")
        if hook.organization_id != org_id:
            raise ForbiddenException("Webhook does not belong to your organisation")
        return WebhookResponse.model_validate(hook)

    # ── Update / Delete ────────────────────────────────────────────────

    async def update_webhook(
        self,
        webhook_id: UUID,
        org_id: UUID,
        data: UpdateWebhookRequest,
    ) -> WebhookResponse:
        hook = await self.hook_repo.get_by_id(webhook_id)
        if not hook:
            raise NotFoundException("Webhook not found")
        if hook.organization_id != org_id:
            raise ForbiddenException("Webhook does not belong to your organisation")

        updates: dict = {}
        if data.url is not None:
            updates["url"] = str(data.url)
        if data.events is not None:
            updates["events"] = data.events
        if data.is_active is not None:
            updates["is_active"] = data.is_active
            if data.is_active:
                # Re-enabling resets failure count
                updates["failure_count"] = 0
                updates["last_failure_reason"] = None

        updated = await self.hook_repo.update(webhook_id, **updates)
        logger.info("webhook.updated", webhook_id=str(webhook_id))
        return WebhookResponse.model_validate(updated)

    async def delete_webhook(self, webhook_id: UUID, org_id: UUID) -> None:
        hook = await self.hook_repo.get_by_id(webhook_id)
        if not hook:
            raise NotFoundException("Webhook not found")
        if hook.organization_id != org_id:
            raise ForbiddenException("Webhook does not belong to your organisation")
        await self.hook_repo.soft_delete(webhook_id)
        logger.info("webhook.deleted", webhook_id=str(webhook_id))

    # ── Dispatch ───────────────────────────────────────────────────────

    async def dispatch_event(
        self,
        org_id: UUID,
        event: str,
        payload: dict,
    ) -> list[UUID]:
        """
        Create WebhookDelivery records for all active webhooks subscribed to
        ``event`` and enqueue a Celery delivery task for each.

        Returns the list of delivery IDs created.
        """
        from app.tasks.webhook import deliver_webhook

        hooks = await self.hook_repo.list_active_for_event(org_id, event)
        if not hooks:
            return []

        delivery_ids: list[UUID] = []
        for hook in hooks:
            delivery = await self.delivery_repo.create(
                webhook_id=hook.id,
                event=event,
                payload=payload,
                status="pending",
                attempts=0,
                created_at=datetime.now(UTC),
            )
            delivery_ids.append(delivery.id)

        # Flush so rows exist in DB before Celery picks them up
        await self.session.flush()

        for del_id in delivery_ids:
            deliver_webhook.delay(str(del_id))
            logger.info("webhook.delivery.queued", delivery_id=str(del_id), event=event)

        return delivery_ids

    # ── Delivery history ───────────────────────────────────────────────

    async def list_deliveries(
        self,
        webhook_id: UUID,
        org_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> WebhookDeliveryListResponse:
        # Ownership check
        hook = await self.hook_repo.get_by_id(webhook_id)
        if not hook:
            raise NotFoundException("Webhook not found")
        if hook.organization_id != org_id:
            raise ForbiddenException("Webhook does not belong to your organisation")

        limit = page_size
        offset = (page - 1) * page_size
        rows, total = await self.delivery_repo.list_by_webhook(
            webhook_id, limit=limit, offset=offset
        )
        total_pages = math.ceil(total / page_size) if page_size else 1
        return WebhookDeliveryListResponse(
            deliveries=[WebhookDeliveryResponse.model_validate(d) for d in rows],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            ),
        )

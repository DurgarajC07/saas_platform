"""
API Management repositories.

APIKeyRepository       — CRUD for api_keys table
WebhookRepository      — CRUD for webhooks table
WebhookDeliveryRepository — CRUD for webhook_deliveries table
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.api_management.models import APIKey, Webhook, WebhookDelivery


# ── APIKeyRepository ────────────────────────────────────────────────────────


class APIKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> APIKey:
        key = APIKey(**kwargs)
        self.session.add(key)
        await self.session.flush()
        await self.session.refresh(key)
        return key

    async def get_by_id(self, key_id: UUID) -> APIKey | None:
        result = await self.session.execute(
            select(APIKey).where(APIKey.id == key_id)
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, key_hash: str) -> APIKey | None:
        """Look up a key by its SHA-256 hash (used during authentication)."""
        result = await self.session.execute(
            select(APIKey).where(APIKey.key_hash == key_hash)
        )
        return result.scalar_one_or_none()

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        include_revoked: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[APIKey], int]:
        stmt = select(APIKey).where(APIKey.organization_id == org_id)
        if not include_revoked:
            stmt = stmt.where(APIKey.revoked_at.is_(None))
        stmt = stmt.order_by(APIKey.created_at.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        rows = (
            await self.session.execute(stmt.offset(offset).limit(limit))
        ).scalars().all()
        return list(rows), total

    async def update_last_used(self, key_id: UUID, ip: str | None = None) -> None:
        await self.session.execute(
            update(APIKey)
            .where(APIKey.id == key_id)
            .values(last_used_at=datetime.now(UTC), last_used_ip=ip)
        )
        await self.session.flush()

    async def revoke(self, key_id: UUID) -> APIKey | None:
        await self.session.execute(
            update(APIKey)
            .where(APIKey.id == key_id)
            .values(is_active=False, revoked_at=datetime.now(UTC))
        )
        await self.session.flush()
        return await self.get_by_id(key_id)


# ── WebhookRepository ───────────────────────────────────────────────────────


class WebhookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> Webhook:
        hook = Webhook(**kwargs)
        self.session.add(hook)
        await self.session.flush()
        await self.session.refresh(hook)
        return hook

    async def get_by_id(self, webhook_id: UUID) -> Webhook | None:
        result = await self.session.execute(
            select(Webhook).where(
                Webhook.id == webhook_id,
                Webhook.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Webhook], int]:
        stmt = (
            select(Webhook)
            .where(Webhook.organization_id == org_id, Webhook.deleted_at.is_(None))
            .order_by(Webhook.created_at.desc())
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(stmt.offset(offset).limit(limit))
        ).scalars().all()
        return list(rows), total

    async def update(self, webhook_id: UUID, **kwargs: Any) -> Webhook | None:
        await self.session.execute(
            update(Webhook)
            .where(Webhook.id == webhook_id, Webhook.deleted_at.is_(None))
            .values(**kwargs)
        )
        await self.session.flush()
        return await self.get_by_id(webhook_id)

    async def soft_delete(self, webhook_id: UUID) -> None:
        await self.session.execute(
            update(Webhook)
            .where(Webhook.id == webhook_id)
            .values(deleted_at=func.now())
        )
        await self.session.flush()

    async def increment_failure(
        self,
        webhook_id: UUID,
        reason: str,
        auto_deactivate_threshold: int = 5,
    ) -> Webhook | None:
        """Bump failure_count; if threshold reached, deactivate the webhook."""
        await self.session.execute(
            update(Webhook)
            .where(Webhook.id == webhook_id, Webhook.deleted_at.is_(None))
            .values(
                failure_count=Webhook.failure_count + 1,
                last_failure_reason=reason,
            )
        )
        await self.session.flush()
        hook = await self.get_by_id(webhook_id)
        if hook and hook.failure_count >= auto_deactivate_threshold and hook.is_active:
            await self.session.execute(
                update(Webhook)
                .where(Webhook.id == webhook_id)
                .values(is_active=False)
            )
            await self.session.flush()
            hook = await self.get_by_id(webhook_id)
        return hook

    async def reset_failure_count(self, webhook_id: UUID) -> None:
        await self.session.execute(
            update(Webhook)
            .where(Webhook.id == webhook_id)
            .values(
                failure_count=0,
                last_failure_reason=None,
                last_triggered_at=datetime.now(UTC),
            )
        )
        await self.session.flush()

    # Return all active webhooks for an org that subscribe to an event
    async def list_active_for_event(
        self, org_id: UUID, event: str
    ) -> list[Webhook]:
        result = await self.session.execute(
            select(Webhook).where(
                Webhook.organization_id == org_id,
                Webhook.is_active.is_(True),
                Webhook.deleted_at.is_(None),
                Webhook.events.contains([event]),
            )
        )
        return list(result.scalars().all())


# ── WebhookDeliveryRepository ───────────────────────────────────────────────


class WebhookDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> WebhookDelivery:
        delivery = WebhookDelivery(**kwargs)
        self.session.add(delivery)
        await self.session.flush()
        await self.session.refresh(delivery)
        return delivery

    async def get_by_id(self, delivery_id: UUID) -> WebhookDelivery | None:
        result = await self.session.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
        )
        return result.scalar_one_or_none()

    async def list_by_webhook(
        self,
        webhook_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WebhookDelivery], int]:
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(stmt.offset(offset).limit(limit))
        ).scalars().all()
        return list(rows), total

    async def update(self, delivery_id: UUID, **kwargs: Any) -> WebhookDelivery | None:
        await self.session.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.id == delivery_id)
            .values(**kwargs)
        )
        await self.session.flush()
        return await self.get_by_id(delivery_id)

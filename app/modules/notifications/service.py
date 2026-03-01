"""
Notification service.

Behaviour spec:
  • send()        — always creates an in_app Notification row, then dispatches
                    Celery tasks for every other enabled channel (email/sms/push).
                    Publishes to Redis Pub/Sub so SSE clients receive real-time delivery.
  • list_notifications — paginated, filterable
  • count_unread  — cheap Redis-cached count for the badge
  • mark_read     — single notification
  • mark_all_read — bulk mark
  • get_preferences  — return user's channel preferences
  • update_preferences — bulk upsert preferences
"""

from __future__ import annotations

import json
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.core.pagination import PaginationParams, paginate
from app.modules.notifications.models import Notification, NotificationPreference
from app.modules.notifications.repository import (
    NotificationPreferenceRepository,
    NotificationRepository,
)
from app.modules.notifications.schemas import (
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationListResponse,
    NotificationPreferenceListResponse,
    NotificationPreferenceResponse,
    NotificationResponse,
    UnreadCountResponse,
    UpdatePreferenceItem,
    UpdatePreferencesResponse,
)
from app.shared.base_schemas import PaginationMeta

logger = structlog.get_logger(__name__)

# Redis channel pattern: notifications:{user_id}
_REDIS_CHANNEL_PREFIX = "notifications"

# Channels that can receive dispatched tasks (not in_app — that's always-on)
_DISPATCHABLE_CHANNELS = ("email", "sms", "push")


class NotificationService:
    """Business logic layer for the notifications module."""

    def __init__(
        self,
        session: AsyncSession,
        redis: aioredis.Redis | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.notif_repo = NotificationRepository(session)
        self.pref_repo = NotificationPreferenceRepository(session)

    # ── Internal channel: Redis Pub/Sub publish ────────────────────────────

    async def _publish(self, user_id: UUID, payload: dict) -> None:
        """Publish notification payload to Redis pub/sub for SSE consumers."""
        if self.redis is None:
            return
        channel = f"{_REDIS_CHANNEL_PREFIX}:{user_id}"
        try:
            await self.redis.publish(channel, json.dumps(payload, default=str))
        except Exception as exc:
            logger.warning("notifications.redis_publish_failed", error=str(exc))

    # ── Send ──────────────────────────────────────────────────────────────

    async def send(
        self,
        *,
        user_id: UUID,
        notification_type: str,
        title: str,
        body: str,
        data: dict | None = None,
        org_id: UUID | None = None,
    ) -> Notification:
        """
        Create an ``in_app`` notification record and dispatch Celery tasks for
        all additional enabled channels.

        Returns the persisted in_app Notification.
        """
        data = data or {}

        # 1. Always create the in_app record
        notif = await self.notif_repo.create(
            user_id=user_id,
            notification_type=notification_type,
            channel="in_app",
            title=title,
            body=body,
            data=data,
            org_id=org_id,
        )

        # 2. Resolve user's channel preferences
        prefs = await self.pref_repo.get_preferences(user_id, notification_type)
        pref_map = {p.channel: p.is_enabled for p in prefs}

        # 3. Dispatch tasks for each enabled external channel
        for ch in _DISPATCHABLE_CHANNELS:
            # A missing preference row = enabled by default
            if pref_map.get(ch, True):
                try:
                    from app.tasks.notifications import dispatch_notification

                    dispatch_notification.delay(
                        str(user_id),
                        notification_type,
                        ch,
                        title,
                        body,
                        data,
                        str(org_id) if org_id else None,
                    )
                    logger.debug(
                        "notifications.dispatched",
                        channel=ch,
                        user_id=str(user_id),
                        type=notification_type,
                    )
                except Exception as exc:
                    # Never let a Celery dispatch failure block the caller
                    logger.warning(
                        "notifications.dispatch_failed",
                        channel=ch,
                        error=str(exc),
                    )

        # 4. Commit the in_app record
        await self.session.commit()
        await self.session.refresh(notif)

        # 5. Publish real-time event to Redis pub/sub for SSE
        await self._publish(
            user_id,
            {
                "id": str(notif.id),
                "type": notification_type,
                "channel": "in_app",
                "title": title,
                "body": body,
                "data": data,
                "created_at": notif.created_at.isoformat(),
            },
        )

        return notif

    # ── List ──────────────────────────────────────────────────────────────

    async def list_notifications(
        self,
        user_id: UUID,
        *,
        org_id: UUID | None = None,
        is_read: bool | None = None,
        notification_type: str | None = None,
        channel: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> NotificationListResponse:
        offset = (page - 1) * page_size
        rows, total = await self.notif_repo.list_for_user(
            user_id,
            org_id=org_id,
            is_read=is_read,
            notification_type=notification_type,
            channel=channel,
            limit=page_size,
            offset=offset,
        )
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        return NotificationListResponse(
            notifications=[NotificationResponse.model_validate(r) for r in rows],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            ),
        )

    # ── Unread count ──────────────────────────────────────────────────────

    async def count_unread(
        self,
        user_id: UUID,
        org_id: UUID | None = None,
    ) -> UnreadCountResponse:
        count = await self.notif_repo.count_unread(user_id, org_id=org_id)
        return UnreadCountResponse(unread_count=count)

    # ── Mark single read ──────────────────────────────────────────────────

    async def mark_read(
        self,
        notif_id: UUID,
        requesting_user_id: UUID,
    ) -> MarkReadResponse:
        notif = await self.notif_repo.mark_read(notif_id, requesting_user_id)
        if notif is None:
            # Try fetching to distinguish 404 vs already-read vs wrong owner
            existing = await self.notif_repo.get_by_id(notif_id)
            if existing is None:
                raise NotFoundException("Notification not found")
            if existing.user_id != requesting_user_id:
                raise ForbiddenException("You do not own this notification")
            # Already read — refresh and return as-is
            notif = existing
        await self.session.commit()
        await self.session.refresh(notif)
        return MarkReadResponse(notification=NotificationResponse.model_validate(notif))

    # ── Mark all read ─────────────────────────────────────────────────────

    async def mark_all_read(
        self,
        user_id: UUID,
        org_id: UUID | None = None,
    ) -> MarkAllReadResponse:
        count = await self.notif_repo.mark_all_read(user_id, org_id=org_id)
        await self.session.commit()
        return MarkAllReadResponse(marked_count=count)

    # ── Preferences ───────────────────────────────────────────────────────

    async def get_preferences(self, user_id: UUID) -> NotificationPreferenceListResponse:
        prefs = await self.pref_repo.get_all_for_user(user_id)
        return NotificationPreferenceListResponse(
            preferences=[NotificationPreferenceResponse.model_validate(p) for p in prefs]
        )

    async def update_preferences(
        self,
        user_id: UUID,
        items: list[UpdatePreferenceItem],
    ) -> UpdatePreferencesResponse:
        updated: list[NotificationPreference] = []
        for item in items:
            if item.channel == "in_app":
                # in_app is always on — silently skip
                continue
            pref = await self.pref_repo.upsert(
                user_id=user_id,
                notification_type=item.notification_type,
                channel=item.channel,
                is_enabled=item.is_enabled,
            )
            updated.append(pref)
        await self.session.commit()
        # Refresh all updated rows
        for p in updated:
            await self.session.refresh(p)
        return UpdatePreferencesResponse(
            preferences=[NotificationPreferenceResponse.model_validate(p) for p in updated]
        )

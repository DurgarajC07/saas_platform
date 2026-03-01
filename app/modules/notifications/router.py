"""
Notifications router.

Registered in main.py at prefix /api/v1.  All routes:

  GET    /notifications              List paginated, filterable notifications
  GET    /notifications/count        Unread in_app count (badge)
  GET    /notifications/stream       SSE stream for real-time delivery
  PUT    /notifications/read-all     Mark all in_app as read
  PUT    /notifications/{id}/read    Mark single notification read
  GET    /notifications/preferences  Return user channel preferences
  PUT    /notifications/preferences  Bulk-upsert channel preferences
"""

from __future__ import annotations

import asyncio
from typing import Annotated, AsyncGenerator
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.dependencies import get_db, get_redis
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.notifications.schemas import (
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationListResponse,
    NotificationPreferenceListResponse,
    NotificationResponse,
    UnreadCountResponse,
    UpdatePreferencesRequest,
    UpdatePreferencesResponse,
)
from app.modules.notifications.service import NotificationService

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── Dependency aliases ────────────────────────────────────────────────────────
CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[aioredis.Redis, Depends(get_redis)]


def _svc(db: DB, redis: Redis) -> NotificationService:
    return NotificationService(db, redis)


SVC = Annotated[NotificationService, Depends(_svc)]


# ─────────────────────────────────────────────────────────────────────────────
# List & Counts
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    summary="List notifications",
    tags=["Notifications"],
)
async def list_notifications(
    current_user: CurrentUser,
    svc: SVC,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_read: bool | None = Query(None, description="Filter by read status"),
    notification_type: str | None = Query(None, description="Filter by notification type"),
    channel: str | None = Query(None, description="Filter by channel (in_app/email/push/sms)"),
) -> NotificationListResponse:
    """Return paginated notifications for the authenticated user."""
    return await svc.list_notifications(
        current_user.id,
        is_read=is_read,
        notification_type=notification_type,
        channel=channel,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/notifications/count",
    response_model=UnreadCountResponse,
    summary="Unread notification count",
    tags=["Notifications"],
)
async def get_unread_count(
    current_user: CurrentUser,
    svc: SVC,
) -> UnreadCountResponse:
    """Return the number of unread in_app notifications. Used for the badge counter."""
    return await svc.count_unread(current_user.id)


# ─────────────────────────────────────────────────────────────────────────────
# Server-Sent Events (SSE)
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/notifications/stream",
    summary="Real-time notification stream (SSE)",
    tags=["Notifications"],
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "SSE stream of notification events",
            "content": {"text/event-stream": {}},
        }
    },
)
async def notification_stream(
    request: Request,
    current_user: CurrentUser,
    redis: Redis,
) -> EventSourceResponse:
    """
    Subscribe to real-time in_app notifications via Server-Sent Events.

    Connection lifecycle:
      • Client connects with ``Authorization: Bearer <token>``.
      • Server subscribes to ``notifications:{user_id}`` Redis pub/sub channel.
      • Every call to ``NotificationService.send()`` publishes to that channel.
      • Client receives the raw JSON payload as an SSE ``data:`` frame.
      • Client disconnect triggers immediate cleanup of the pub/sub subscription.

    SSE event format::

        data: {"id": "...", "type": "billing.alert", "title": "...", ...}\n\n

    Keepalive pings are sent every 30 seconds to detect dead connections.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        pubsub = redis.pubsub()
        channel = f"notifications:{current_user.id}"
        await pubsub.subscribe(channel)

        logger.info(
            "notifications.sse.connected",
            user_id=str(current_user.id),
            channel=channel,
        )

        try:
            # Yield a connected confirmation event first
            yield {"event": "connected", "data": f'{{"channel": "{channel}"}}'}

            while True:
                # Check if the client disconnected
                if await request.is_disconnected():
                    break

                # Poll for a message with a short timeout so we can check
                # client disconnect frequently.
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )

                if message and message["type"] == "message":
                    raw = message["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    yield {"event": "notification", "data": raw}
                else:
                    # Send a keepalive comment every ~30 s to avoid proxy timeouts.
                    # sse-starlette ignores dict with no ``data`` key — yield a
                    # comment string directly.
                    yield {"event": "ping", "data": ""}

                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            logger.info(
                "notifications.sse.disconnected",
                user_id=str(current_user.id),
            )

    return EventSourceResponse(event_generator())


# ─────────────────────────────────────────────────────────────────────────────
# Mark read
# ─────────────────────────────────────────────────────────────────────────────


@router.put(
    "/notifications/read-all",
    response_model=MarkAllReadResponse,
    summary="Mark all notifications as read",
    tags=["Notifications"],
)
async def mark_all_read(
    current_user: CurrentUser,
    svc: SVC,
) -> MarkAllReadResponse:
    """Mark all unread in_app notifications as read for the authenticated user."""
    return await svc.mark_all_read(current_user.id)


@router.put(
    "/notifications/{notification_id}/read",
    response_model=MarkReadResponse,
    summary="Mark a notification as read",
    tags=["Notifications"],
)
async def mark_notification_read(
    notification_id: UUID,
    current_user: CurrentUser,
    svc: SVC,
) -> MarkReadResponse:
    """Mark a specific notification as read. Returns 403 if it belongs to another user."""
    return await svc.mark_read(notification_id, current_user.id)


# ─────────────────────────────────────────────────────────────────────────────
# Preferences
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/notifications/preferences",
    response_model=NotificationPreferenceListResponse,
    summary="Get notification preferences",
    tags=["Notifications"],
)
async def get_preferences(
    current_user: CurrentUser,
    svc: SVC,
) -> NotificationPreferenceListResponse:
    """Return the current user's notification channel preferences."""
    return await svc.get_preferences(current_user.id)


@router.put(
    "/notifications/preferences",
    response_model=UpdatePreferencesResponse,
    summary="Update notification preferences",
    tags=["Notifications"],
)
async def update_preferences(
    body: UpdatePreferencesRequest,
    current_user: CurrentUser,
    svc: SVC,
) -> UpdatePreferencesResponse:
    """
    Bulk-upsert channel preferences.

    Send a list of ``{notificationType, channel, isEnabled}`` objects.
    The ``in_app`` channel is always enabled and cannot be disabled.
    """
    return await svc.update_preferences(current_user.id, body.preferences)


# ─────────────────────────────────────────────────────────────────────────────
# Internal / test helper
# ─────────────────────────────────────────────────────────────────────────────


from pydantic import BaseModel as _BaseModel  # noqa: E402 — local import to avoid circular


class _SendTestRequest(_BaseModel):
    type: str = "system.test"
    title: str = "Test notification"
    body: str = "This is a test"
    data: dict = {}


@router.post(
    "/notifications/test-send",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a test notification (internal / dev use)",
    include_in_schema=True,
    tags=["Notifications"],
)
async def send_test_notification(
    body: _SendTestRequest,
    current_user: CurrentUser,
    svc: SVC,
) -> NotificationResponse:
    """
    Creates an in_app notification for the authenticated user.
    Used for verifying the notifications pipeline end-to-end.
    Celery tasks for other channels are dispatched as normal
    (they will be no-ops / stubs in dev unless a worker is running).
    """
    notif = await svc.send(
        user_id=current_user.id,
        notification_type=body.type,
        title=body.title,
        body=body.body,
        data=body.data,
        org_id=None,
    )
    return NotificationResponse.model_validate(notif)

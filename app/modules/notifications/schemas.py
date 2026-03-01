"""
Notifications module Pydantic schemas.

All models use CamelModel → camelCase JSON output.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import field_validator

from app.shared.base_schemas import CamelModel, PaginationMeta


# ──────────────────────────────────────────────────────────────────────────────
# Notification
# ──────────────────────────────────────────────────────────────────────────────


class NotificationResponse(CamelModel):
    """A single notification (in_app or delivery record)."""

    id: UUID
    user_id: UUID
    organization_id: UUID | None
    type: str
    channel: str
    title: str | None
    body: str | None
    data: dict
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(CamelModel):
    notifications: list[NotificationResponse]
    pagination: PaginationMeta


class UnreadCountResponse(CamelModel):
    unread_count: int


class MarkReadResponse(CamelModel):
    notification: NotificationResponse


class MarkAllReadResponse(CamelModel):
    marked_count: int


# ──────────────────────────────────────────────────────────────────────────────
# Preferences
# ──────────────────────────────────────────────────────────────────────────────


class NotificationPreferenceResponse(CamelModel):
    """A single preference row: user × type × channel."""

    id: UUID
    user_id: UUID
    notification_type: str
    channel: str
    is_enabled: bool


class NotificationPreferenceListResponse(CamelModel):
    preferences: list[NotificationPreferenceResponse]


class UpdatePreferenceItem(CamelModel):
    """One entry in the bulk-update preferences request."""

    notification_type: str
    channel: str
    is_enabled: bool


class UpdatePreferencesRequest(CamelModel):
    preferences: list[UpdatePreferenceItem]


class UpdatePreferencesResponse(CamelModel):
    preferences: list[NotificationPreferenceResponse]


# ──────────────────────────────────────────────────────────────────────────────
# Internal send request (used by other services calling NotificationService)
# ──────────────────────────────────────────────────────────────────────────────


class SendNotificationRequest(CamelModel):
    """Used by internal callers (other services) to send a notification."""

    user_id: UUID
    type: str
    title: str
    body: str
    data: dict = {}
    org_id: UUID | None = None

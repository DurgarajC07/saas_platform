"""
Notifications repository layer.

NotificationRepository      — CRUD for Notification rows
NotificationPreferenceRepository — CRUD for NotificationPreference rows
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification, NotificationPreference


# ── NotificationRepository ─────────────────────────────────────────────────


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Write ─────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        user_id: UUID,
        notification_type: str,
        channel: str,
        title: str | None,
        body: str | None,
        data: dict,
        org_id: UUID | None,
    ) -> Notification:
        notif = Notification(
            user_id=user_id,
            organization_id=org_id,
            type=notification_type,
            channel=channel,
            title=title,
            body=body,
            data=data or {},
            is_read=False,
            created_at=datetime.now(UTC),
        )
        self.session.add(notif)
        await self.session.flush()
        return notif

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_by_id(self, notif_id: UUID) -> Notification | None:
        result = await self.session.execute(
            select(Notification).where(Notification.id == notif_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        org_id: UUID | None = None,
        is_read: bool | None = None,
        notification_type: str | None = None,
        channel: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        conditions = [Notification.user_id == user_id]

        if org_id is not None:
            conditions.append(Notification.organization_id == org_id)
        if is_read is not None:
            conditions.append(Notification.is_read == is_read)
        if notification_type is not None:
            conditions.append(Notification.type == notification_type)
        if channel is not None:
            conditions.append(Notification.channel == channel)

        where_clause = and_(*conditions)

        # total count
        count_result = await self.session.execute(
            select(func.count()).select_from(Notification).where(where_clause)
        )
        total: int = count_result.scalar_one()

        # page
        rows_result = await self.session.execute(
            select(Notification)
            .where(where_clause)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list(rows_result.scalars().all())
        return rows, total

    async def count_unread(self, user_id: UUID, org_id: UUID | None = None) -> int:
        conditions = [
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
            Notification.channel == "in_app",
        ]
        if org_id is not None:
            conditions.append(Notification.organization_id == org_id)
        result = await self.session.execute(
            select(func.count())
            .select_from(Notification)
            .where(and_(*conditions))
        )
        return result.scalar_one()

    # ── Mark read ─────────────────────────────────────────────────────────

    async def mark_read(self, notif_id: UUID, user_id: UUID) -> Notification | None:
        """Mark a single notification as read (ownership-checked)."""
        await self.session.execute(
            update(Notification)
            .where(
                Notification.id == notif_id,
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        await self.session.flush()
        return await self.get_by_id(notif_id)

    async def mark_all_read(self, user_id: UUID, org_id: UUID | None = None) -> int:
        """Mark all in_app notifications for a user as read. Returns updated count."""
        conditions = [
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
            Notification.channel == "in_app",
        ]
        if org_id is not None:
            conditions.append(Notification.organization_id == org_id)

        result = await self.session.execute(
            update(Notification)
            .where(and_(*conditions))
            .values(is_read=True, read_at=datetime.now(UTC))
            .returning(Notification.id)
        )
        await self.session.flush()
        return len(list(result.all()))


# ── NotificationPreferenceRepository ──────────────────────────────────────


class NotificationPreferenceRepository:
    """
    Manages per-user, per-type, per-channel preferences.

    Default behaviour: a missing row means *enabled* so new notification
    types work without forcing users to configure first.
    """

    _ALL_CHANNELS = ("email", "sms", "push")  # in_app is always-on

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all_for_user(self, user_id: UUID) -> list[NotificationPreference]:
        """Return every preference row for this user."""
        result = await self.session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id
            )
        )
        return list(result.scalars().all())

    async def get_preferences(
        self, user_id: UUID, notification_type: str
    ) -> list[NotificationPreference]:
        """
        Return preferences for a specific notification type.
        Only rows that exist in the DB are returned — callers treat a
        missing row as *enabled by default*.
        """
        result = await self.session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.notification_type == notification_type,
            )
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        user_id: UUID,
        notification_type: str,
        channel: str,
        is_enabled: bool,
    ) -> NotificationPreference:
        """Insert or update a single preference row."""
        result = await self.session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.notification_type == notification_type,
                NotificationPreference.channel == channel,
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = NotificationPreference(
                user_id=user_id,
                notification_type=notification_type,
                channel=channel,
                is_enabled=is_enabled,
            )
            self.session.add(pref)
        else:
            pref.is_enabled = is_enabled
        await self.session.flush()
        return pref

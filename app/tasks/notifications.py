"""
Celery tasks — notification channel dispatch.

dispatch_notification(user_id, notification_type, channel, title, body, data)
  • email  → SMTP via aiosmtplib
  • push   → FCM stub (logs intent; real integration requires FCM credentials)
  • sms    → Twilio stub (logs intent; real integration requires Twilio credentials)

All tasks:
  • Create a Notification row for the channel (so delivery is recorded).
  • Retry up to 3 times with exponential back-off on transient failures.
  • Never propagate exceptions back to the Celery broker silently
    — errors are logged and the notification row is updated with a
    ``failed`` status note in the ``data`` field.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from uuid import UUID

import structlog

from app.core.celery_app import celery_app
from app.config import get_settings

logger = structlog.get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _create_channel_notification(
    user_id: UUID,
    notification_type: str,
    channel: str,
    title: str,
    body: str,
    data: dict,
    org_id: UUID | None,
    status_note: str = "delivered",
) -> None:
    """Persist a Notification row for the dispatched channel delivery."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from app.modules.notifications.repository import NotificationRepository

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=2)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as session:
            repo = NotificationRepository(session)
            await repo.create(
                user_id=user_id,
                notification_type=notification_type,
                channel=channel,
                title=title,
                body=body,
                data={**data, "_delivery_status": status_note},
                org_id=org_id,
            )
            await session.commit()
    finally:
        await engine.dispose()


# ── Email delivery ─────────────────────────────────────────────────────────────


async def _send_email_async(
    to_email: str,
    title: str,
    body: str,
) -> None:
    """Send a plain-text + HTML email via SMTP."""
    settings = get_settings()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email

    text_part = MIMEText(body, "plain")
    html_part = MIMEText(
        f"<html><body><p>{body}</p></body></html>",
        "html",
    )
    msg.attach(text_part)
    msg.attach(html_part)

    def _send_sync() -> None:
        if settings.SMTP_TLS:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as s:
                if settings.SMTP_USER:
                    s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                s.sendmail(settings.SMTP_FROM_EMAIL, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as s:
                if settings.SMTP_USER:
                    s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                s.sendmail(settings.SMTP_FROM_EMAIL, [to_email], msg.as_string())

    # Run sync SMTP in a thread executor to avoid blocking the event loop
    import asyncio

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_sync)


# ── Main Celery task ───────────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.notifications.dispatch_notification",
    max_retries=3,
    default_retry_delay=60,
    queue="notifications",
    acks_late=True,
)
def dispatch_notification(
    self,
    user_id: str,
    notification_type: str,
    channel: str,
    title: str,
    body: str,
    data: dict,
    org_id: str | None = None,
) -> None:
    """
    Celery task: dispatch a notification to the given channel.

    Args:
        user_id:           UUID string of the recipient.
        notification_type: E.g. ``billing.alert``, ``security.login``.
        channel:           One of ``email``, ``push``, ``sms``.
        title:             Short subject / heading.
        body:              Notification body text.
        data:              Arbitrary JSON payload for the notification.
        org_id:            Optional organisation context UUID string.
    """
    retry_count = self.request.retries

    async def _run() -> None:
        uid = UUID(user_id)
        oid = UUID(org_id) if org_id else None

        if channel == "email":
            # Resolve the user's email address
            from sqlalchemy.ext.asyncio import (
                AsyncSession,
                async_sessionmaker,
                create_async_engine,
            )
            from sqlalchemy import select
            from app.modules.auth.models import User
            from app.config import get_settings as _gs

            settings = _gs()
            engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=2)
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            try:
                async with factory() as session:
                    result = await session.execute(select(User).where(User.id == uid))
                    user = result.scalar_one_or_none()
                    to_email = user.email if user else None
            finally:
                await engine.dispose()

            if not to_email:
                logger.warning(
                    "dispatch_notification: user not found, skipping email",
                    user_id=user_id,
                )
                return

            try:
                await _send_email_async(to_email, title, body)
                await _create_channel_notification(
                    uid, notification_type, "email", title, body, data, oid,
                    status_note="delivered",
                )
                logger.info(
                    "dispatch_notification.email.sent",
                    user_id=user_id,
                    to=to_email,
                    type=notification_type,
                )
            except Exception as exc:
                await _create_channel_notification(
                    uid, notification_type, "email", title, body, data, oid,
                    status_note=f"failed: {exc}",
                )
                raise

        elif channel == "push":
            # FCM / APNs stub — log intent; wire real credentials when available
            logger.info(
                "dispatch_notification.push.stub",
                user_id=user_id,
                type=notification_type,
                title=title,
            )
            await _create_channel_notification(
                uid, notification_type, "push", title, body, data, oid,
                status_note="stub_logged",
            )

        elif channel == "sms":
            # Twilio stub — log intent; wire real credentials when available
            logger.info(
                "dispatch_notification.sms.stub",
                user_id=user_id,
                type=notification_type,
                title=title,
            )
            await _create_channel_notification(
                uid, notification_type, "sms", title, body, data, oid,
                status_note="stub_logged",
            )
        else:
            logger.warning(
                "dispatch_notification: unknown channel",
                channel=channel,
                user_id=user_id,
            )

    try:
        asyncio.run(_run())
    except Exception as exc:
        countdown = 60 * (2 ** retry_count)  # 60 → 120 → 240 s
        logger.warning(
            "dispatch_notification.retry",
            channel=channel,
            user_id=user_id,
            retry=retry_count,
            countdown=countdown,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown)

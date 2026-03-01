"""
Celery tasks — transactional email delivery.

Tasks:
  send_verification_email    – email verification link after registration
  send_invitation_email      – org invitation with accept link
  send_password_reset_email  – password reset link

All tasks:
  • Queue: «email», priority HIGH.
  • Retry up to 3 times with exponential back-off.
  • Use the shared SMTP helper from app.core.utils.email.
"""

from __future__ import annotations

import asyncio
import structlog

from app.core.celery_app import celery_app

logger = structlog.get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run(coro):  # noqa: ANN001
    """Execute a coroutine synchronously inside a Celery worker."""
    return asyncio.run(coro)


# ── send_verification_email ────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.email.send_verification_email",
    max_retries=3,
    default_retry_delay=30,
    queue="email",
    acks_late=True,
)
def send_verification_email_task(self, to: str, token: str, user_name: str = "") -> dict:
    """
    Send an account email-verification link.

    Args:
        to:        Recipient email address.
        token:     Raw verification token (will be embedded in the URL).
        user_name: Optional display name for personalisation.
    """
    try:
        return _run(_send_verification(to=to, token=token, user_name=user_name))
    except Exception as exc:
        delay = 30 * (2 ** self.request.retries)
        logger.warning(
            "email.verification.retry",
            to=to,
            attempt=self.request.retries + 1,
            delay=delay,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=delay)


async def _send_verification(*, to: str, token: str, user_name: str) -> dict:
    from app.core.utils.email import send_verification_email
    await send_verification_email(to=to, token=token)
    logger.info("email.verification.sent", to=to)
    return {"sent": True, "to": to}


# ── send_invitation_email ──────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.email.send_invitation_email",
    max_retries=3,
    default_retry_delay=30,
    queue="email",
    acks_late=True,
)
def send_invitation_email_task(
    self,
    to: str,
    invited_by: str,
    org_name: str,
    accept_token: str,
) -> dict:
    """
    Send an organisation invitation email with an accept link.

    Args:
        to:           Invitee email address.
        invited_by:   Display name of the inviter.
        org_name:     Organisation name.
        accept_token: Token embedded in the accept URL.
    """
    try:
        return _run(
            _send_invitation(
                to=to,
                invited_by=invited_by,
                org_name=org_name,
                accept_token=accept_token,
            )
        )
    except Exception as exc:
        delay = 30 * (2 ** self.request.retries)
        logger.warning("email.invitation.retry", to=to, error=str(exc))
        raise self.retry(exc=exc, countdown=delay)


async def _send_invitation(
    *, to: str, invited_by: str, org_name: str, accept_token: str
) -> dict:
    from app.config import get_settings
    from app.core.utils.email import send_email

    settings = get_settings()
    accept_url = f"{settings.FRONTEND_URL}/accept-invitation?token={accept_token}"

    html = f"""
    <html><body style="font-family: sans-serif; color: #333; max-width: 600px; margin: auto;">
      <h2>You've been invited to join {org_name}</h2>
      <p>{invited_by} has invited you to collaborate on <strong>{org_name}</strong>.</p>
      <p style="text-align:center; margin: 32px 0;">
        <a href="{accept_url}"
           style="background:#4F46E5; color:#fff; padding:12px 28px;
                  border-radius:6px; text-decoration:none; font-weight:bold;">
          Accept Invitation
        </a>
      </p>
      <p>Or copy this URL:<br><a href="{accept_url}">{accept_url}</a></p>
      <hr>
      <p style="font-size:12px; color:#888;">
        This invitation expires in 7 days. If you did not expect this email, you can safely ignore it.
      </p>
    </body></html>
    """
    text = (
        f"You've been invited to join {org_name} by {invited_by}.\n\n"
        f"Accept here: {accept_url}\n\n"
        "This invitation expires in 7 days."
    )

    await send_email(
        to=to,
        subject=f"You've been invited to join {org_name}",
        html_body=html,
        text_body=text,
    )
    logger.info("email.invitation.sent", to=to, org=org_name)
    return {"sent": True, "to": to}


# ── send_password_reset_email ──────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.email.send_password_reset_email",
    max_retries=3,
    default_retry_delay=30,
    queue="email",
    acks_late=True,
)
def send_password_reset_email_task(self, to: str, token: str, user_name: str = "") -> dict:
    """
    Send a password reset link.

    Args:
        to:        Recipient email address.
        token:     Raw reset token.
        user_name: Optional display name.
    """
    try:
        return _run(_send_password_reset(to=to, token=token, user_name=user_name))
    except Exception as exc:
        delay = 30 * (2 ** self.request.retries)
        logger.warning("email.password_reset.retry", to=to, error=str(exc))
        raise self.retry(exc=exc, countdown=delay)


async def _send_password_reset(*, to: str, token: str, user_name: str) -> dict:
    from app.core.utils.email import send_password_reset_email
    await send_password_reset_email(to=to, token=token)
    logger.info("email.password_reset.sent", to=to)
    return {"sent": True, "to": to}

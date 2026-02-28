"""
Async email helpers.

Sends transactional emails over SMTP using Python's built-in smtplib run in a
thread executor so it never blocks the async event loop.

In production, swap the _send() inner functions for Celery task dispatches to
get retries, queuing, and distributed execution without changing call sites.

Usage::

    from app.core.utils.email import send_verification_email, send_password_reset_email
    await send_verification_email(to="user@example.com", token="<raw_token>")
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


# ── Low-level SMTP send ────────────────────────────────────────────────────

async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    text_body: str = "",
) -> None:
    """
    Send a single email via SMTP.
    Runs the blocking SMTP call in a ThreadPoolExecutor so it is safe to await.
    Failures are logged but never re-raised — email must not fail a request.
    """
    settings = get_settings()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    def _blocking_send() -> None:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            if settings.SMTP_TLS:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _blocking_send)
        logger.info("email_sent", to=to, subject=subject)
    except Exception as exc:
        # Log but swallow — email delivery is best-effort at this layer
        logger.error("email_send_failed", to=to, subject=subject, error=str(exc))


# ── Auth-specific email templates ──────────────────────────────────────────

async def send_verification_email(to: str, token: str) -> None:
    """Send an account email-verification link."""
    settings = get_settings()
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"

    html = f"""
    <html><body style="font-family: sans-serif; color: #333; max-width: 600px; margin: auto;">
      <h2>Verify your email address</h2>
      <p>Thanks for signing up! Click the button below to verify your email address.
         This link expires in <strong>24 hours</strong>.</p>
      <p style="text-align:center; margin: 32px 0;">
        <a href="{verify_url}"
           style="background:#4F46E5; color:#fff; padding:12px 28px;
                  border-radius:6px; text-decoration:none; font-weight:bold;">
          Verify Email
        </a>
      </p>
      <p>Or copy this URL into your browser:<br>
         <a href="{verify_url}">{verify_url}</a></p>
      <hr>
      <p style="font-size:12px; color:#888;">
        If you did not create an account, you can safely ignore this email.
      </p>
    </body></html>
    """
    text = (
        f"Verify your email: {verify_url}\n\n"
        "This link expires in 24 hours."
    )
    await send_email(
        to=to,
        subject="Verify your email address",
        html_body=html,
        text_body=text,
    )


async def send_password_reset_email(to: str, token: str) -> None:
    """Send a password-reset link."""
    settings = get_settings()
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"

    html = f"""
    <html><body style="font-family: sans-serif; color: #333; max-width: 600px; margin: auto;">
      <h2>Reset your password</h2>
      <p>We received a request to reset the password for your account.
         Click below to choose a new password.
         This link expires in <strong>30 minutes</strong>.</p>
      <p style="text-align:center; margin: 32px 0;">
        <a href="{reset_url}"
           style="background:#DC2626; color:#fff; padding:12px 28px;
                  border-radius:6px; text-decoration:none; font-weight:bold;">
          Reset Password
        </a>
      </p>
      <p>Or copy this URL into your browser:<br>
         <a href="{reset_url}">{reset_url}</a></p>
      <hr>
      <p style="font-size:12px; color:#888;">
        If you did not request this, please ignore this email.
        Your password will not change.
      </p>
    </body></html>
    """
    text = (
        f"Reset your password: {reset_url}\n\n"
        "This link expires in 30 minutes."
    )
    await send_email(
        to=to,
        subject="Reset your password",
        html_body=html,
        text_body=text,
    )

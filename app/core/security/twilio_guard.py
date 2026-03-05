"""
Twilio HMAC Guard — FastAPI dependency that enforces X-Twilio-Signature
validation on every inbound Twilio webhook request.

Security contract
─────────────────
  • Returns **HTTP 401** (Unauthorized) when the signature header is absent
    or does not match — never 403 (which would expose that a route exists
    but the caller lacks permission; 401 indicates the request origin is
    not trusted).

  • Returns **HTTP 503** (Service Unavailable) when ``TWILIO_AUTH_TOKEN``
    is not configured in the application settings.  This prevents webhooks
    being silently accepted without validation due to a misconfiguration.

  • The raw request body / form is **not consumed** by this dependency; it
    is still available to the endpoint handler via ``request.body()`` or
    ``request.form()``.

Usage in an endpoint
────────────────────
    from app.core.security.twilio_guard import validate_twilio_signature

    @router.post("/webhooks/twilio/inbound/{phone_number}", include_in_schema=False)
    async def my_webhook(
        phone_number: str,
        request: Request,
        db: DB,
        _: None = Depends(validate_twilio_signature),
    ) -> Response:
        form = await request.form()
        ...

Alternatively call :func:`check_twilio_signature` from endpoint body code
when you need to pass the already-parsed form dict directly.
"""
from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import Depends, Header, Request
from fastapi.responses import Response

from app.config import get_settings
from app.core.exceptions import ServiceUnavailableException

log = structlog.get_logger(__name__)


def _get_validator():
    try:
        from twilio.request_validator import RequestValidator
        return RequestValidator
    except ImportError:
        return None


def check_twilio_signature(
    url: str,
    params: dict,
    signature: str,
    auth_token: str,
) -> bool:
    """
    Validate a Twilio HMAC-SHA1 signature.

    Parameters
    ----------
    url:
        The fully-qualified URL Twilio POSTed to (including scheme + host).
    params:
        The parsed form body as a plain ``dict[str, str]``.
    signature:
        Value of the ``X-Twilio-Signature`` header.
    auth_token:
        The Twilio Auth Token for this account.

    Returns ``True`` when the signature is valid, ``False`` otherwise.
    Raises ``RuntimeError`` when the ``twilio`` package is not installed.
    """
    Validator = _get_validator()
    if Validator is None:
        raise RuntimeError(
            "twilio package is not installed — cannot validate webhook signatures"
        )
    validator = Validator(auth_token)
    return validator.validate(url, params, signature)


async def validate_twilio_signature(request: Request) -> None:
    """
    FastAPI dependency — validate the ``X-Twilio-Signature`` header.

    Raises :class:`HTTPException` 401 when the signature is absent or invalid.
    Raises :class:`HTTPException` 503 when ``TWILIO_AUTH_TOKEN`` is not set.

    .. note::
        This dependency **reads** the request form body to build the params
        dict required by Twilio's validation algorithm.  The Starlette Request
        object caches the body, so calling ``await request.form()`` a second
        time in the endpoint handler is safe and returns the same data.
    """
    settings = get_settings()

    if not settings.TWILIO_AUTH_TOKEN:
        log.error("twilio_guard.missing_auth_token")
        raise ServiceUnavailableException(
            "TWILIO_AUTH_TOKEN is not configured; webhook cannot be validated"
        )

    sig = request.headers.get("X-Twilio-Signature", "")
    if not sig:
        log.warning("twilio_guard.missing_signature", url=str(request.url))
        from fastapi import HTTPException
        raise HTTPException(
            status_code=401,
            detail="Missing X-Twilio-Signature header",
        )

    try:
        form = await request.form()
        params = dict(form)
        url = str(request.url)
        valid = check_twilio_signature(url, params, sig, settings.TWILIO_AUTH_TOKEN)
    except RuntimeError as exc:
        log.error("twilio_guard.validator_unavailable", error=str(exc))
        raise ServiceUnavailableException(str(exc)) from exc
    except Exception as exc:
        log.error("twilio_guard.validation_error", error=str(exc))
        from fastapi import HTTPException
        raise HTTPException(
            status_code=401,
            detail="Twilio signature validation failed",
        ) from exc

    if not valid:
        log.warning(
            "twilio_guard.invalid_signature",
            url=url,
            sig_prefix=sig[:8] + "…" if len(sig) > 8 else sig,
        )
        from fastapi import HTTPException
        raise HTTPException(
            status_code=401,
            detail="Invalid X-Twilio-Signature",
        )

    log.debug("twilio_guard.signature_ok", url=url)


# Annotated type alias for use as a dependency
TwilioSigned = Annotated[None, Depends(validate_twilio_signature)]

"""
Agents module — webhook event publishers.

Each function:
1. Publishes a JSON payload to the Redis ``live_calls:{org_id}`` pub/sub
   channel so the SSE endpoint can stream it to connected browsers.
2. Fires the corresponding webhook event via ``WebhookService.dispatch_event``
   so any registered customer webhooks receive the notification.

All functions are ``async`` and accept an open SQLAlchemy ``AsyncSession``
plus a connected ``redis.asyncio.Redis`` client.  They **never raise** — any
error is logged and swallowed so call-lifecycle code is never blocked by
a notification failure.

Supported event names
─────────────────────
  call.started            — call connected to the agent pipeline
  call.ended              — call finished (includes duration + transcript URL)
  call.failed             — call terminated with an error
  agent.limit_warning     — org has used ≥ 80 % of monthly call-minute quota
  agent.limit_exceeded    — org hit the monthly quota; new calls are blocked
  kb.ingestion.complete   — a knowledge-base document finished processing
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)

_LIVE_CALLS_CHANNEL = "live_calls:{org_id}"


async def _publish_redis(redis, channel: str, payload: dict) -> None:
    """Publish a JSON payload to a Redis channel.  Swallows errors."""
    try:
        await redis.publish(channel, json.dumps(payload, default=str))
    except Exception as exc:  # noqa: BLE001
        log.warning("events.redis_publish_failed", channel=channel, error=str(exc))


async def _dispatch_webhook(session, org_id: UUID, event: str, payload: dict) -> None:
    """Fire webhook deliveries for *event*.  Swallows errors."""
    try:
        from app.modules.api_management.service import WebhookService

        svc = WebhookService(session)
        await svc.dispatch_event(org_id, event, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("events.webhook_dispatch_failed", event=event, error=str(exc))


# ── call.started ──────────────────────────────────────────────────────────────

async def publish_call_started(
    session,
    redis,
    org_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    direction: str = "inbound",
    transport: str = "websocket",
    metadata: dict | None = None,
) -> None:
    """
    Fired when the pipeline signals that a call is now live.

    The pipeline service publishes to Redis *before* calling this function
    when it creates/connects a session.  This function additionally fires
    customer webhooks.
    """
    payload: dict = {
        "event": "call.started",
        "org_id": str(org_id),
        "agent_id": str(agent_id),
        "call_id": str(call_id),
        "direction": direction,
        "transport": transport,
        "metadata": metadata or {},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    channel = _LIVE_CALLS_CHANNEL.format(org_id=org_id)
    await _publish_redis(redis, channel, payload)
    await _dispatch_webhook(session, org_id, "call.started", payload)
    log.info("event.call.started", call_id=str(call_id), agent_id=str(agent_id))


# ── call.ended ────────────────────────────────────────────────────────────────

async def publish_call_ended(
    session,
    redis,
    org_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    duration_sec: int | None,
    transcript_url: str | None = None,
    recording_url: str | None = None,
    metadata: dict | None = None,
) -> None:
    """
    Fired when a call completes normally.

    The ``call.ended`` webhook payload includes ``duration_sec``,
    ``transcript_url``, and ``recording_url`` so webhook consumers can
    retrieve the call artefacts without an extra API call.
    """
    payload: dict = {
        "event": "call.ended",
        "org_id": str(org_id),
        "agent_id": str(agent_id),
        "call_id": str(call_id),
        "duration_sec": duration_sec,
        "transcript_url": transcript_url,
        "recording_url": recording_url,
        "metadata": metadata or {},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    channel = _LIVE_CALLS_CHANNEL.format(org_id=org_id)
    await _publish_redis(redis, channel, payload)
    await _dispatch_webhook(session, org_id, "call.ended", payload)
    log.info(
        "event.call.ended",
        call_id=str(call_id),
        duration_sec=duration_sec,
    )


# ── call.failed ───────────────────────────────────────────────────────────────

async def publish_call_failed(
    session,
    redis,
    org_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    reason: str,
    metadata: dict | None = None,
) -> None:
    """Fired when a call terminates with an error."""
    payload: dict = {
        "event": "call.failed",
        "org_id": str(org_id),
        "agent_id": str(agent_id),
        "call_id": str(call_id),
        "reason": reason,
        "metadata": metadata or {},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    channel = _LIVE_CALLS_CHANNEL.format(org_id=org_id)
    await _publish_redis(redis, channel, payload)
    await _dispatch_webhook(session, org_id, "call.failed", payload)
    log.warning("event.call.failed", call_id=str(call_id), reason=reason)


# ── agent.limit_warning ───────────────────────────────────────────────────────

async def publish_limit_warning(
    session,
    redis,
    org_id: UUID,
    agent_id: UUID,
    percent_used: float,
) -> None:
    """
    Fired when the org has consumed ≥ 80 % of its monthly call-minute quota.

    Only fires once per calendar month (deduplication via Redis key).
    """
    dedup_key = f"limit_warning_fired:{org_id}:{datetime.now(UTC).strftime('%Y-%m')}"
    already_fired = await redis.get(dedup_key)
    if already_fired:
        return

    payload: dict = {
        "event": "agent.limit_warning",
        "org_id": str(org_id),
        "agent_id": str(agent_id),
        "percent_used": round(percent_used, 2),
        "threshold": 80,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    channel = _LIVE_CALLS_CHANNEL.format(org_id=org_id)
    await _publish_redis(redis, channel, payload)
    await _dispatch_webhook(session, org_id, "agent.limit_warning", payload)

    # Set dedup key for the rest of the month (32 days to be safe)
    await redis.setex(dedup_key, 32 * 24 * 3600, "1")
    log.warning("event.agent.limit_warning", org_id=str(org_id), pct=percent_used)


# ── agent.limit_exceeded ──────────────────────────────────────────────────────

async def publish_limit_exceeded(
    session,
    redis,
    org_id: UUID,
    agent_id: UUID,
) -> None:
    """Fired when the org has hit the monthly quota and new calls are blocked."""
    payload: dict = {
        "event": "agent.limit_exceeded",
        "org_id": str(org_id),
        "agent_id": str(agent_id),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    channel = _LIVE_CALLS_CHANNEL.format(org_id=org_id)
    await _publish_redis(redis, channel, payload)
    await _dispatch_webhook(session, org_id, "agent.limit_exceeded", payload)
    log.error("event.agent.limit_exceeded", org_id=str(org_id), agent_id=str(agent_id))


# ── kb.ingestion.complete ─────────────────────────────────────────────────────

async def publish_kb_ingestion_complete(
    session,
    redis,
    org_id: UUID,
    agent_id: UUID,
    doc_id: UUID,
    chunk_count: int,
) -> None:
    """Fired when a knowledge-base document has finished being processed."""
    payload: dict = {
        "event": "kb.ingestion.complete",
        "org_id": str(org_id),
        "agent_id": str(agent_id),
        "doc_id": str(doc_id),
        "chunk_count": chunk_count,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    channel = _LIVE_CALLS_CHANNEL.format(org_id=org_id)
    await _publish_redis(redis, channel, payload)
    await _dispatch_webhook(session, org_id, "kb.ingestion.complete", payload)
    log.info(
        "event.kb.ingestion.complete",
        doc_id=str(doc_id),
        chunks=chunk_count,
    )

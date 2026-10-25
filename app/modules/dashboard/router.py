"""
Dashboard module router.

Registered in main.py at prefix /api/v1 so routes resolve to:

  Dashboard (org-scoped analytics)
  ─────────────────────────────────────────────────────────────────────────
  GET  /api/v1/dashboard/overview          Active calls, usage, top agents
  GET  /api/v1/dashboard/latency           P50/P95/P99 latency last 24 h
  GET  /api/v1/dashboard/call-volume       Call count by hour/day/month
  GET  /api/v1/dashboard/agent-performance Per-agent success rate + latency
  GET  /api/v1/agents/{id}/analytics       Deep-dive for a single agent

  Live call monitoring (SSE)
  ─────────────────────────────────────────────────────────────────────────
  GET  /api/v1/calls/live                  Server-Sent Events stream

  Admin (platform superadmin only)
  ─────────────────────────────────────────────────────────────────────────
  GET  /api/v1/admin/gpu-status            NVML GPU metrics
  GET  /api/v1/admin/queue-status          Celery queue depths
  POST /api/v1/admin/model-benchmark       Run latency benchmark
"""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime
from typing import Annotated, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.core.dependencies import get_db, get_redis
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.rbac.dependencies import get_current_org_id, require
from app.modules.dashboard.schemas import (
    AgentDeepDiveResponse,
    AgentPerformanceResponse,
    CallVolumeResponse,
    GPUStatusResponse,
    LatencyResponse,
    ModelBenchmarkRequest,
    ModelBenchmarkResponse,
    OverviewResponse,
    QueueStatusResponse,
)
from app.modules.dashboard.service import AdminService, DashboardService

try:
    from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]
    _SSE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SSE_AVAILABLE = False
    EventSourceResponse = None  # type: ignore[assignment,misc]

router = APIRouter()

# ── Type aliases ──────────────────────────────────────────────────────────────

CurrentUser = Annotated[User, Depends(get_current_user)]
OrgID       = Annotated[UUID, Depends(get_current_org_id)]
DB          = Annotated[AsyncSession, Depends(get_db)]
Redis       = Annotated[aioredis.Redis, Depends(get_redis)]

AdminUser   = Annotated[User, require("system.admin")]
DashReadUser = Annotated[User, require("agents.agent.read")]


# ── Dashboard overview ────────────────────────────────────────────────────────

@router.get(
    "/dashboard/overview",
    response_model=OverviewResponse,
    summary="Dashboard overview",
    tags=["Dashboard"],
)
async def dashboard_overview(
    actor: DashReadUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> OverviewResponse:
    """
    Return the real-time overview card for the dashboard home page.

    Includes active call count (from Redis), monthly totals derived from
    ``call_logs``, and the top-5 agents by call volume.
    """
    svc = DashboardService(db, redis)
    return await svc.overview(org_id)


# ── Latency chart ─────────────────────────────────────────────────────────────

@router.get(
    "/dashboard/latency",
    response_model=LatencyResponse,
    summary="Latency chart data (last 24 h)",
    tags=["Dashboard"],
)
async def dashboard_latency(
    actor: DashReadUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> LatencyResponse:
    """
    Return P50 / P95 / P99 STT, LLM, and TTS latencies for the last 24 hours,
    bucketed by hour.  The ``summary`` field contains the aggregate over the
    whole window.
    """
    svc = DashboardService(db, redis)
    return await svc.latency_24h(org_id)


# ── Call volume chart ─────────────────────────────────────────────────────────

@router.get(
    "/dashboard/call-volume",
    response_model=CallVolumeResponse,
    summary="Call volume chart data",
    tags=["Dashboard"],
)
async def dashboard_call_volume(
    actor: DashReadUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
    granularity: str = Query(
        default="day",
        pattern="^(hour|day|month)$",
        description="Bucket size: hour | day | month",
    ),
    days: int = Query(
        default=30,
        ge=1,
        le=365,
        description="Number of days to look back.",
    ),
) -> CallVolumeResponse:
    """Return call volume bucketed by hour, day, or month."""
    svc = DashboardService(db, redis)
    return await svc.call_volume(org_id, granularity=granularity, days=days)


# ── Agent performance table ───────────────────────────────────────────────────

@router.get(
    "/dashboard/agent-performance",
    response_model=AgentPerformanceResponse,
    summary="Per-agent performance table",
    tags=["Dashboard"],
)
async def dashboard_agent_performance(
    actor: DashReadUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
    days: int = Query(
        default=30,
        ge=1,
        le=365,
        description="Look-back window in days.",
    ),
) -> AgentPerformanceResponse:
    """
    Return success rate, avg duration, and average STT/LLM/TTS latency for
    every agent in the organisation, sorted by call volume descending.
    """
    svc = DashboardService(db, redis)
    return await svc.agent_performance(org_id, days=days)


# ── Agent deep-dive ───────────────────────────────────────────────────────────

@router.get(
    "/agents/{agent_id}/analytics/deep-dive",
    response_model=AgentDeepDiveResponse,
    summary="Agent analytics deep-dive",
    tags=["Dashboard"],
)
async def agent_analytics(
    agent_id: UUID,
    actor: DashReadUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
    days: int = Query(default=30, ge=1, le=365),
) -> AgentDeepDiveResponse:
    """
    Return a full latency breakdown (P50/P95/P99 for STT, LLM, TTS) plus
    up to five recent transcript snippets for a single agent.
    """
    svc = DashboardService(db, redis)
    return await svc.agent_deep_dive(agent_id, org_id, days=days)


# ── Live call SSE ─────────────────────────────────────────────────────────────
#
# Browsers' native EventSource API cannot attach an Authorization header or a
# custom X-Org-ID header to the request it makes — both of which the normal
# auth dependencies (DashReadUser / OrgID) require. That made GET /calls/live
# unreachable from any real browser regardless of how the token was passed.
# Fix: a short-lived, single-use ticket. The client calls POST
# /dashboard/live-calls/ticket first (normal Bearer + X-Org-ID auth, fully
# permission-checked there), then opens the SSE connection with
# ?ticket=<ticket> — no long-lived credential ever appears in the URL or
# browser history, and the ticket is useless after 30s or one use.

_SSE_TICKET_TTL_SEC = 30


def _sse_ticket_key(ticket: str) -> str:
    return f"sse_ticket:{ticket}"


@router.post(
    "/dashboard/live-calls/ticket",
    summary="Issue a short-lived ticket for the live-call SSE stream",
    tags=["Dashboard"],
)
async def issue_live_calls_ticket(
    actor: DashReadUser,
    org_id: OrgID,
    redis: Redis,
) -> dict[str, str]:
    ticket = secrets.token_urlsafe(24)
    await redis.set(_sse_ticket_key(ticket), str(org_id), ex=_SSE_TICKET_TTL_SEC)
    return {"ticket": ticket}


@router.get(
    "/calls/live",
    summary="Live call SSE stream",
    tags=["Dashboard"],
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-Sent Events stream of live call events.",
        }
    },
)
async def live_calls_stream(
    redis: Redis,
    ticket: str = Query(..., description="Ticket from POST /dashboard/live-calls/ticket"),
):
    """
    Stream real-time call events (call.started, call.ended, call.failed) via
    Server-Sent Events.

    The pipeline service publishes JSON payloads to the Redis channel
    ``live_calls:{org_id}`` whenever a call changes state.  This endpoint
    subscribes to that channel and forwards each message to the browser.

    Clients should reconnect automatically on disconnect (SSE spec behaviour);
    reconnecting means fetching a fresh ticket, since each one is single-use.
    """
    org_id_raw = await redis.getdel(_sse_ticket_key(ticket))
    if not org_id_raw:
        raise HTTPException(status_code=401, detail="Invalid or expired SSE ticket")
    org_id = UUID(org_id_raw if isinstance(org_id_raw, str) else org_id_raw.decode())

    if not _SSE_AVAILABLE:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            "sse-starlette is not installed; add it to requirements.txt",
            status_code=503,
        )

    channel = f"live_calls:{org_id}"

    async def generator() -> AsyncGenerator[str, None]:
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            # Emit an initial keepalive so the browser confirms the connection
            yield json.dumps({"event": "connected", "channel": channel})
            while True:
                # get_message(timeout=30) actually blocks for up to 30s rather
                # than the no-op `async for ... ; sleep(0)` this replaced —
                # that previous version never sent a keepalive during a quiet
                # channel, so proxies with an idle-connection timeout would
                # silently drop the stream.
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                if message is None:
                    yield json.dumps({"event": "keepalive"})
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                yield data
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return EventSourceResponse(generator())


# ── Admin — GPU status ────────────────────────────────────────────────────────

@router.get(
    "/admin/gpu-status",
    response_model=GPUStatusResponse,
    summary="GPU VRAM + temperature status",
    tags=["Admin"],
)
async def gpu_status(
    actor: AdminUser,
) -> GPUStatusResponse:
    """
    Return live GPU metrics via NVML (pynvml).

    Returns ``nvml_available=false`` when the host has no NVIDIA GPU or the
    pynvml package is not installed.
    """
    return AdminService.gpu_status()


# ── Admin — Queue status ──────────────────────────────────────────────────────

@router.get(
    "/admin/queue-status",
    response_model=QueueStatusResponse,
    summary="Celery queue depths",
    tags=["Admin"],
)
async def queue_status(
    actor: AdminUser,
) -> QueueStatusResponse:
    """
    Return Celery queue depths (pending, active, reserved tasks) for each
    named queue.  Worker count is derived from the Celery inspect response.
    """
    return AdminService.queue_status()


# ── Admin — Model benchmark ───────────────────────────────────────────────────

@router.post(
    "/admin/model-benchmark",
    response_model=ModelBenchmarkResponse,
    summary="Run real-time model latency benchmark",
    tags=["Admin"],
)
async def model_benchmark(
    body: ModelBenchmarkRequest,
    actor: AdminUser,
) -> ModelBenchmarkResponse:
    """
    Run a synthetic latency benchmark against the pipeline service for the
    requested model.  Results vary by hardware; use for relative comparison
    between model versions.
    """
    return await AdminService.run_model_benchmark(body)

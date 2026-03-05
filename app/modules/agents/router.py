"""
Agents module router.

Registered in main.py at prefix /api/v1 so routes resolve to:

  Agents
  ─────────────────────────────────────────────────────────────────────────
  POST   /api/v1/agents                              Create agent
  GET    /api/v1/agents                              List org agents (paginated)
  GET    /api/v1/agents/{agent_id}                   Agent detail + live status
  PATCH  /api/v1/agents/{agent_id}                   Update any config field
  DELETE /api/v1/agents/{agent_id}                   Soft delete
  POST   /api/v1/agents/{agent_id}/test-call         Issue WebSocket test URL
  POST   /api/v1/agents/{agent_id}/webrtc/connect     WebRTC SDP exchange (browser → pipeline)
  PUT    /api/v1/agents/{agent_id}/prompt            Update system prompt only
  POST   /api/v1/agents/{agent_id}/phone-numbers     Assign phone number
  GET    /api/v1/agents/{agent_id}/phone-numbers     List phone numbers
  POST   /api/v1/agents/{agent_id}/knowledge-base    Upload document (multipart, queued)
  GET    /api/v1/agents/{agent_id}/knowledge-base    List KB documents + status
  DELETE /api/v1/agents/{agent_id}/knowledge-base    Clear entire knowledge base
  DELETE /api/v1/agents/{agent_id}/knowledge-base/{doc_id}  Delete single document
  PUT    /api/v1/agents/{agent_id}/tools             Replace tool definitions
  GET    /api/v1/agents/{agent_id}/calls             Paginated call history
  GET    /api/v1/agents/{agent_id}/analytics         Latency + volume stats

  Calls
  ─────────────────────────────────────────────────────────────────────────
  POST   /api/v1/calls                               Write call log (pipeline)
  GET    /api/v1/calls/{call_id}                     Single call detail
  GET    /api/v1/calls/{call_id}/recording           Presigned recording URL

  Twilio PSTN
  ────────────────────────────────────────────────────────────────────────
  POST   /api/v1/webhooks/twilio/inbound/{phone_number}  Twilio inbound webhook
  POST   /api/v1/webhooks/twilio/connect/{session_id}   TwiML connect callback
  POST   /api/v1/agents/{agent_id}/calls/outbound        Initiate outbound call

All endpoints require a valid JWT (Bearer token) and an org context header.
RBAC permissions: agents.<resource>.<action>
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.core.dependencies import get_db, get_redis
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.features.dependencies import require_feature
from app.modules.rbac.dependencies import get_current_org_id, require
from app.modules.agents.credits import CallCreditService
from app.modules.agents.schemas import (
    AgentAnalyticsResponse,
    AgentListResponse,
    AgentPhoneNumberResponse,
    AgentResponse,
    AssignPhoneNumberRequest,
    CallLogListResponse,
    CallLogResponse,
    CallMinutesUsageResponse,
    CreateAgentRequest,
    KbDeleteDocResponse,
    KbDocumentListResponse,
    KbUploadResponse,
    OutboundCallRequest,
    OutboundCallResponse,
    RecordingUrlResponse,
    TestCallResponse,
    UpdateAgentRequest,
    UpdatePromptRequest,
    UpdateToolsRequest,
    WebRTCConnectResponse,
    WebRTCOfferRequest,
    WriteCallLogRequest,
)
from app.modules.agents.service import AgentService, CallLogService, TwilioCallService
from app.modules.agents.kb_service import KnowledgeBaseService

router = APIRouter()

# ── Type aliases ─────────────────────────────────────────────────────────────

CurrentUser = Annotated[User, Depends(get_current_user)]
OrgID = Annotated[UUID, Depends(get_current_org_id)]
DB = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[aioredis.Redis, Depends(get_redis)]

# Permission-guarded user aliases
AgentCreateUser = Annotated[User, require("agents.agent.create")]
AgentReadUser = Annotated[User, require("agents.agent.read")]
AgentUpdateUser = Annotated[User, require("agents.agent.update")]
AgentDeleteUser = Annotated[User, require("agents.agent.delete")]
AgentListUser = Annotated[User, require("agents.agent.list")]
CallLogWriteUser = Annotated[User, require("agents.call_log.create")]
CallLogReadUser = Annotated[User, require("agents.call_log.read")]
UsageReadUser = Annotated[User, require("agents.usage.read")]


# ═══════════════════════════════════════════════════════════════════════════
# AGENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/agents",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create agent",
    tags=["Agents"],
)
async def create_agent(
    body: CreateAgentRequest,
    actor: AgentCreateUser,
    org_id: OrgID,
    db: DB,
    _feat: None = require_feature("ai.agents.create"),
) -> AgentResponse:
    """
    Create a new AI voice-agent with full pipeline configuration.

    The ``slug`` field must be unique within the organisation; if omitted it
    is auto-generated from the agent name.
    """
    svc = AgentService(db)
    return await svc.create_agent(org_id, actor, body)


@router.get(
    "/agents",
    response_model=AgentListResponse,
    summary="List agents",
    tags=["Agents"],
)
async def list_agents(
    actor: AgentListUser,
    org_id: OrgID,
    db: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    agent_type: str | None = Query(default=None),
) -> AgentListResponse:
    """List all agents for the organisation. Filterable by status and type."""
    svc = AgentService(db)
    return await svc.list_agents(
        org_id,
        page=page,
        page_size=page_size,
        status=status_filter,
        agent_type=agent_type,
    )


@router.get(
    "/agents/{agent_id}",
    response_model=AgentResponse,
    summary="Get agent",
    tags=["Agents"],
)
async def get_agent(
    agent_id: UUID,
    actor: AgentReadUser,
    org_id: OrgID,
    db: DB,
) -> AgentResponse:
    """Return the full configuration for a single agent."""
    svc = AgentService(db)
    return await svc.get_agent(agent_id, org_id)


@router.patch(
    "/agents/{agent_id}",
    response_model=AgentResponse,
    summary="Update agent",
    tags=["Agents"],
)
async def update_agent(
    agent_id: UUID,
    body: UpdateAgentRequest,
    actor: AgentUpdateUser,
    org_id: OrgID,
    db: DB,
) -> AgentResponse:
    """
    Partially update agent configuration.

    Only fields present in the request body are written; omitted fields keep
    their current value.  The pipeline picks up changes on the next call.
    """
    svc = AgentService(db)
    return await svc.update_agent(agent_id, org_id, body, actor=actor)


@router.delete(
    "/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete agent",
    tags=["Agents"],
)
async def delete_agent(
    agent_id: UUID,
    actor: AgentDeleteUser,
    org_id: OrgID,
    db: DB,
) -> None:
    """
    Soft-delete an agent (status → archived, deleted_at set).

    Any in-progress calls are allowed to finish in the pipeline service.
    Deleted agents are excluded from the list endpoint.
    """
    svc = AgentService(db)
    await svc.delete_agent(agent_id, org_id, actor=actor)


# ── Test call ────────────────────────────────────────────────────────────────


@router.post(
    "/agents/{agent_id}/test-call",
    response_model=TestCallResponse,
    summary="Issue test-call WebSocket URL",
    tags=["Agents"],
)
async def test_call(
    agent_id: UUID,
    actor: AgentUpdateUser,
    org_id: OrgID,
    db: DB,
) -> TestCallResponse:
    """
    Generate a one-time, short-lived WebSocket URL for a test call.

    The client opens ``ws_url`` directly — the pipeline service validates the
    token and streams audio in both directions.  URL expires in 300 seconds.
    """
    svc = AgentService(db)
    return await svc.test_call(agent_id, org_id)


# ── WebRTC connect ────────────────────────────────────────────────────────────


@router.post(
    "/agents/{agent_id}/webrtc/connect",
    response_model=WebRTCConnectResponse,
    summary="Initiate WebRTC call to agent",
    tags=["Agents"],
    status_code=status.HTTP_200_OK,
)
async def webrtc_connect(
    agent_id: UUID,
    body: WebRTCOfferRequest,
    actor: AgentReadUser,
    org_id: OrgID,
    db: DB,
    _feat: None = require_feature("ai.webrtc.enabled"),
) -> WebRTCConnectResponse:
    """
    Exchange an SDP offer/answer with the pipeline service to establish a
    WebRTC audio call directly from the browser.

    The browser flow:
      1. Call ``navigator.mediaDevices.getUserMedia({audio: true})`` to get
         the local audio track.
      2. Create an ``RTCPeerConnection`` and add the audio track.
      3. Call ``createOffer()`` and ``setLocalDescription()``.
      4. POST this endpoint with ``{sdp, type}`` from the local description.
      5. Set the returned ``sdp`` as the remote description.
      6. Audio now flows bidirectionally over SRTP.

    Returns the SDP answer and an ICE server list.
    """
    svc = AgentService(db)
    return await svc.webrtc_connect(agent_id, org_id, body)


# ── Prompt ───────────────────────────────────────────────────────────────────


@router.put(
    "/agents/{agent_id}/prompt",
    response_model=AgentResponse,
    summary="Update system prompt",
    tags=["Agents"],
)
async def update_prompt(
    agent_id: UUID,
    body: UpdatePromptRequest,
    actor: AgentUpdateUser,
    org_id: OrgID,
    db: DB,
) -> AgentResponse:
    """Replace the agent's system prompt. Effective on the next call."""
    svc = AgentService(db)
    return await svc.update_prompt(agent_id, org_id, body)


# ── Phone numbers ────────────────────────────────────────────────────────────


@router.post(
    "/agents/{agent_id}/phone-numbers",
    response_model=AgentPhoneNumberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign phone number",
    tags=["Agents"],
)
async def assign_phone_number(
    agent_id: UUID,
    body: AssignPhoneNumberRequest,
    actor: AgentUpdateUser,
    org_id: OrgID,
    db: DB,
    _feat: None = require_feature("ai.pstn.enabled"),
) -> AgentPhoneNumberResponse:
    """Associate an E.164 phone number with the agent."""
    svc = AgentService(db)
    return await svc.assign_phone_number(agent_id, org_id, body)


@router.get(
    "/agents/{agent_id}/phone-numbers",
    response_model=list[AgentPhoneNumberResponse],
    summary="List phone numbers",
    tags=["Agents"],
)
async def list_phone_numbers(
    agent_id: UUID,
    actor: AgentReadUser,
    org_id: OrgID,
    db: DB,
) -> list[AgentPhoneNumberResponse]:
    """List all phone numbers assigned to an agent."""
    svc = AgentService(db)
    return await svc.list_phone_numbers(agent_id, org_id)


# ── Knowledge base ───────────────────────────────────────────────────────────


@router.post(
    "/agents/{agent_id}/knowledge-base",
    response_model=KbUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload document to agent knowledge base",
    tags=["Agents"],
)
async def upload_knowledge_base(
    agent_id: UUID,
    actor: AgentUpdateUser,
    org_id: OrgID,
    db: DB,
    file: UploadFile = File(..., description="Document to ingest (PDF, DOCX, TXT, MD, CSV)"),
    source_url: str | None = Query(default=None, description="Source URL for url/youtube types"),
    _feat: None = require_feature("ai.rag.enabled"),
) -> KbUploadResponse:
    """
    Upload a document and queue it for ingestion into the agent's Qdrant
    knowledge-base collection.

    The response is immediate (202); ingestion runs in the background via
    a Celery worker.  Poll **GET /knowledge-base** to track progress.

    Supported formats: `pdf`, `docx`, `txt`, `md`, `csv`, `url`, `youtube`.
    """
    svc = KnowledgeBaseService(db)
    return await svc.upload_document(
        agent_id=agent_id,
        org_id=org_id,
        file=file,
        source_url=source_url,
    )


@router.get(
    "/agents/{agent_id}/knowledge-base",
    response_model=KbDocumentListResponse,
    summary="List knowledge-base documents",
    tags=["Agents"],
)
async def list_knowledge_base(
    agent_id: UUID,
    actor: AgentReadUser,
    org_id: OrgID,
    db: DB,
    kb_status: str | None = Query(default=None, alias="status"),
    _feat: None = require_feature("ai.rag.enabled"),
) -> KbDocumentListResponse:
    """
    Return all documents in the agent's knowledge base with their ingestion
    status (``pending`` | ``processing`` | ``completed`` | ``failed``).
    """
    svc = KnowledgeBaseService(db)
    return await svc.list_documents(agent_id=agent_id, org_id=org_id, status=kb_status)


@router.delete(
    "/agents/{agent_id}/knowledge-base/{doc_id}",
    response_model=KbDeleteDocResponse,
    summary="Delete a single knowledge-base document",
    tags=["Agents"],
)
async def delete_kb_document(
    agent_id: UUID,
    doc_id: UUID,
    actor: AgentUpdateUser,
    org_id: OrgID,
    db: DB,
    _feat: None = require_feature("ai.rag.enabled"),
) -> KbDeleteDocResponse:
    """
    Remove a single document from the agent's knowledge base.

    All Qdrant vector points associated with the document are deleted, and
    the metadata record is removed from the database.
    """
    svc = KnowledgeBaseService(db)
    return await svc.delete_document(agent_id=agent_id, org_id=org_id, doc_id=doc_id)


@router.delete(
    "/agents/{agent_id}/knowledge-base",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear entire agent knowledge base",
    tags=["Agents"],
)
async def clear_knowledge_base(
    agent_id: UUID,
    actor: AgentUpdateUser,
    org_id: OrgID,
    db: DB,
    _feat: None = require_feature("ai.rag.enabled"),
) -> None:
    """
    Drop the agent's entire Qdrant collection and remove all knowledge-base
    document records.  This is irreversible — all ingested content is deleted.
    """
    svc = KnowledgeBaseService(db)
    await svc.clear_all(agent_id=agent_id, org_id=org_id)


# ── Tools ────────────────────────────────────────────────────────────────────


@router.put(
    "/agents/{agent_id}/tools",
    response_model=AgentResponse,
    summary="Update function tool definitions",
    tags=["Agents"],
)
async def update_tools(
    agent_id: UUID,
    body: UpdateToolsRequest,
    actor: AgentUpdateUser,
    org_id: OrgID,
    db: DB,
    _feat: None = require_feature("ai.tools.enabled"),
) -> AgentResponse:
    """Replace the full OpenAI-format tool definition array for the agent."""
    svc = AgentService(db)
    return await svc.update_tools(agent_id, org_id, body, actor=actor)


# ── Usage / quota dashboard ───────────────────────────────────────────────────


@router.get(
    "/agents/usage/minutes",
    response_model=CallMinutesUsageResponse,
    summary="Organisation call-minute usage dashboard",
    tags=["Agents"],
)
async def get_minutes_usage(
    actor: UsageReadUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> CallMinutesUsageResponse:
    """
    Return the organisation's AI call-minute consumption for the current
    calendar month and the plan's monthly limit.

    ``allowed_minutes = null`` means the plan has an unlimited quota.
    Intended for dashboard widgets and pre-call quota warnings.
    """
    svc = CallCreditService(db, redis)
    usage = await svc.get_usage(org_id)

    used_seconds = int(await redis.get(f"call_minutes:{org_id}:{datetime.now(UTC).strftime('%Y-%m')}") or 0)
    allowed = usage.allowed_minutes

    if allowed is not None and allowed > 0:
        remaining: int | None = max(0, allowed - usage.used_minutes)
        percent: float | None = round(min(usage.used_minutes / allowed * 100, 100.0), 1)
    else:
        remaining = None
        percent = None

    return CallMinutesUsageResponse(
        org_id=org_id,
        billing_period=datetime.now(UTC).strftime("%Y-%m"),
        used_minutes=usage.used_minutes,
        used_seconds=used_seconds,
        allowed_minutes=allowed,
        remaining_minutes=remaining,
        percent_used=percent,
    )


# ── Call history & analytics ─────────────────────────────────────────────────


@router.get(
    "/agents/{agent_id}/calls",
    response_model=CallLogListResponse,
    summary="List agent call logs",
    tags=["Agents"],
)
async def list_agent_calls(
    agent_id: UUID,
    actor: CallLogReadUser,
    org_id: OrgID,
    db: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
) -> CallLogListResponse:
    """Paginated call log for a specific agent."""
    svc = CallLogService(db)
    return await svc.list_calls(
        agent_id,
        org_id,
        page=page,
        page_size=page_size,
        status=status_filter,
    )


@router.get(
    "/agents/{agent_id}/analytics",
    response_model=AgentAnalyticsResponse,
    summary="Agent analytics",
    tags=["Agents"],
)
async def agent_analytics(
    agent_id: UUID,
    actor: AgentReadUser,
    org_id: OrgID,
    db: DB,
    days: int = Query(default=30, ge=1, le=365),
) -> AgentAnalyticsResponse:
    """
    Return latency statistics (STT / LLM TTFT / TTS TTFB) and call volume
    for ``?days=N`` (default 30).

    All percentile calculations run as a single aggregate SQL query against
    the call_logs table — no external metric store required.
    """
    svc = CallLogService(db)
    return await svc.get_analytics(agent_id, org_id, period_days=days)


# ═══════════════════════════════════════════════════════════════════════════
# CALL ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/calls",
    response_model=CallLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Write call log",
    tags=["Calls"],
)
async def write_call_log(
    body: WriteCallLogRequest,
    actor: CallLogWriteUser,
    db: DB,
) -> CallLogResponse:
    """
    Called by the pipeline service at the end of every session.

    Persists the call record including latency metrics, transcript, and any
    recording URL.  No org-context header required — org_id is in the body.
    """
    svc = CallLogService(db)
    return await svc.write_call_log(body)


@router.get(
    "/calls/{call_id}",
    response_model=CallLogResponse,
    summary="Get call detail",
    tags=["Calls"],
)
async def get_call(
    call_id: UUID,
    actor: CallLogReadUser,
    org_id: OrgID,
    db: DB,
) -> CallLogResponse:
    """Return a single call record with full transcript and latency metrics."""
    svc = CallLogService(db)
    return await svc.get_call(call_id, org_id)


@router.get(
    "/calls/{call_id}/recording",
    response_model=RecordingUrlResponse,
    summary="Get presigned recording URL",
    tags=["Calls"],
)
async def get_recording_url(
    call_id: UUID,
    actor: CallLogReadUser,
    org_id: OrgID,
    db: DB,
) -> RecordingUrlResponse:
    """
    Return a presigned URL granting temporary read access to the call
    recording stored in MinIO / S3.

    URL is valid for 1 hour.
    """
    svc = CallLogService(db)
    return await svc.get_recording_url(call_id, org_id)


# ── Twilio PSTN endpoints ─────────────────────────────────────────────────────

@router.post(
    "/webhooks/twilio/inbound/{phone_number}",
    response_class=Response,
    include_in_schema=False,  # public webhook – no JWT
    tags=["Twilio"],
)
async def twilio_inbound_webhook(
    phone_number: str,
    request: Request,
    org_id: OrgID,
    db: DB,
) -> Response:
    """
    Twilio inbound-call webhook.

    Twilio POSTs here (form-encoded body) when a call arrives on a number
    assigned to one of the organisation's agents.  The handler validates the
    ``X-Twilio-Signature`` header, looks up the agent, creates a pipeline
    session, and returns TwiML ``<Connect><Stream …/>`` XML.
    """
    from app.config import get_settings

    settings = get_settings()
    svc = TwilioCallService(db)

    # Validate Twilio signature when a token is configured
    if settings.TWILIO_AUTH_TOKEN:
        sig = request.headers.get("X-Twilio-Signature", "")
        form = await request.form()
        params = dict(form)
        url = str(request.url)
        if not svc.validate_signature(url, params, sig):
            return Response(content="Forbidden", status_code=403)

    form = await request.form()
    call_sid: str = form.get("CallSid", "")
    from_number: str = form.get("From", "")

    twiml = await svc.handle_inbound(
        phone_number=phone_number,
        call_sid=call_sid,
        from_number=from_number,
        org_id=org_id,
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/webhooks/twilio/connect/{session_id}",
    response_class=Response,
    include_in_schema=False,  # called by Twilio for outbound connect
    tags=["Twilio"],
)
async def twilio_connect_callback(
    session_id: str,
    db: DB,
) -> Response:
    """
    Outbound call TwiML connect callback.

    Twilio calls this URL when the callee answers an outbound call.
    Returns the same ``<Connect><Stream>`` TwiML as inbound calls so the
    pipeline handles both directions identically.
    """
    svc = TwilioCallService(db)
    twiml = svc._twiml_stream(session_id)
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/agents/{agent_id}/calls/outbound",
    response_model=OutboundCallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate outbound call",
    tags=["Twilio"],
)
async def start_outbound_call(
    agent_id: UUID,
    body: OutboundCallRequest,
    actor: Annotated[User, require("agents.agent.read")],
    org_id: OrgID,
    db: DB,
    _feature: None = require_feature("ai.pstn.enabled"),
) -> OutboundCallResponse:
    """
    Initiate an outbound PSTN call from an agent to a phone number.

    The agent must have at least one Twilio phone number assigned, and the
    organisation must have the ``ai.pstn.enabled`` feature flag enabled.

    Returns the Twilio ``CallSid``, pipeline ``session_id``, and the
    caller-ID used so the client can track or cancel the call.
    """
    svc = TwilioCallService(db)
    return await svc.start_outbound_call(
        agent_id=agent_id,
        org_id=org_id,
        data=body,
        actor_id=actor.id,
    )

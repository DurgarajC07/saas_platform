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

All endpoints require a valid JWT (Bearer token) and an org context header.
RBAC permissions: agents.<resource>.<action>
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.rbac.dependencies import get_current_org_id, require
from app.modules.agents.schemas import (
    AgentAnalyticsResponse,
    AgentListResponse,
    AgentPhoneNumberResponse,
    AgentResponse,
    AssignPhoneNumberRequest,
    CallLogListResponse,
    CallLogResponse,
    CreateAgentRequest,
    KbDeleteDocResponse,
    KbDocumentListResponse,
    KbUploadResponse,
    RecordingUrlResponse,
    TestCallResponse,
    UpdateAgentRequest,
    UpdatePromptRequest,
    UpdateToolsRequest,
    WebRTCConnectResponse,
    WebRTCOfferRequest,
    WriteCallLogRequest,
)
from app.modules.agents.service import AgentService, CallLogService
from app.modules.agents.kb_service import KnowledgeBaseService

router = APIRouter()

# ── Type aliases ─────────────────────────────────────────────────────────────

CurrentUser = Annotated[User, Depends(get_current_user)]
OrgID = Annotated[UUID, Depends(get_current_org_id)]
DB = Annotated[AsyncSession, Depends(get_db)]

# Permission-guarded user aliases
AgentCreateUser = Annotated[User, require("agents.agent.create")]
AgentReadUser = Annotated[User, require("agents.agent.read")]
AgentUpdateUser = Annotated[User, require("agents.agent.update")]
AgentDeleteUser = Annotated[User, require("agents.agent.delete")]
AgentListUser = Annotated[User, require("agents.agent.list")]
CallLogWriteUser = Annotated[User, require("agents.call_log.create")]
CallLogReadUser = Annotated[User, require("agents.call_log.read")]


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
    return await svc.update_agent(agent_id, org_id, body)


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
    await svc.delete_agent(agent_id, org_id)


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
) -> AgentResponse:
    """Replace the full OpenAI-format tool definition array for the agent."""
    svc = AgentService(db)
    return await svc.update_tools(agent_id, org_id, body)


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

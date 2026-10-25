"""
Agents module Pydantic schemas.

Agent:
  CreateAgentRequest / UpdateAgentRequest / AgentResponse / AgentListResponse

AgentPhoneNumber:
  AssignPhoneNumberRequest / AgentPhoneNumberResponse

CallLog:
  WriteCallLogRequest / CallLogResponse / CallLogListResponse

KnowledgeBase:
  KbDocumentResponse / KbDocumentListResponse / KbUploadResponse / KbDeleteDocResponse

Analytics:
  AgentAnalyticsResponse

Prompt / Tools shortcuts:
  UpdatePromptRequest / UpdateToolsRequest
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.shared.base_schemas import CamelModel, PaginationMeta


# ── Agent type / status enums ────────────────────────────────────────────────

AGENT_TYPES = frozenset({"speaker_only", "conversational", "rag_bot", "db_bot"})
AGENT_STATUSES = frozenset({"draft", "active", "paused", "archived"})
NOISE_LEVELS = frozenset({"none", "rnnoise", "deepfilternet"})
PHONE_PROVIDERS = frozenset({"twilio", "vonage", "own"})
CALL_DIRECTIONS = frozenset({"inbound", "outbound"})
CALL_TRANSPORTS = frozenset({"webrtc", "websocket", "twilio"})
CALL_STATUSES = frozenset({"connected", "completed", "failed", "no-answer"})


# ═══════════════════════════════════════════════════════════════════════════
# AGENT SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════


class CreateAgentRequest(CamelModel):
    """Full agent configuration supplied at creation time."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(
        None,
        pattern=r"^[a-z0-9-]+$",
        max_length=255,
        description="URL-safe slug — auto-generated from name if omitted",
    )
    agent_type: str = Field(default="conversational")
    status: str = Field(default="draft")

    # LLM
    llm_model: str = Field(default="qwen2.5:3b", max_length=100)
    system_prompt: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=32_768)

    # STT
    language: str | None = Field(None, max_length=10)

    # TTS
    tts_voice: str = Field(default="af_heart", max_length=100)
    tts_speed: float = Field(default=1.0, ge=0.25, le=4.0)

    # VAD
    vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    min_speech_ms: int = Field(default=250, ge=50, le=5_000)
    silence_ms: int = Field(default=800, ge=100, le=10_000)
    allow_interruptions: bool = True

    # Noise
    noise_removal_level: str = Field(default="none")

    # RAG
    qdrant_collection: str | None = Field(None, max_length=255)
    rag_top_k: int = Field(default=3, ge=1, le=20)

    # Function tools (OpenAI-format tool definition array or null)
    tools_json: list[dict[str, Any]] | None = None

    # Call config
    welcome_message: str | None = None
    max_call_duration_sec: int = Field(default=300, ge=10, le=7_200)
    record_calls: bool = True

    # Extras
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_type")
    @classmethod
    def validate_agent_type(cls, v: str) -> str:
        if v not in AGENT_TYPES:
            raise ValueError(f"agent_type must be one of {sorted(AGENT_TYPES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in AGENT_STATUSES:
            raise ValueError(f"status must be one of {sorted(AGENT_STATUSES)}")
        return v

    @field_validator("noise_removal_level")
    @classmethod
    def validate_noise(cls, v: str) -> str:
        if v not in NOISE_LEVELS:
            raise ValueError(f"noise_removal_level must be one of {sorted(NOISE_LEVELS)}")
        return v


class UpdateAgentRequest(CamelModel):
    """
    Partial-update body — every field is optional.
    PATCH semantics: only supplied fields are written.
    """

    name: str | None = Field(None, min_length=1, max_length=255)
    slug: str | None = Field(None, pattern=r"^[a-z0-9-]+$", max_length=255)
    agent_type: str | None = None
    status: str | None = None

    llm_model: str | None = Field(None, max_length=100)
    system_prompt: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=1, le=32_768)

    language: str | None = Field(None, max_length=10)

    tts_voice: str | None = Field(None, max_length=100)
    tts_speed: float | None = Field(None, ge=0.25, le=4.0)

    vad_threshold: float | None = Field(None, ge=0.0, le=1.0)
    min_speech_ms: int | None = Field(None, ge=50, le=5_000)
    silence_ms: int | None = Field(None, ge=100, le=10_000)
    allow_interruptions: bool | None = None

    noise_removal_level: str | None = None

    qdrant_collection: str | None = Field(None, max_length=255)
    rag_top_k: int | None = Field(None, ge=1, le=20)

    tools_json: list[dict[str, Any]] | None = None

    welcome_message: str | None = None
    max_call_duration_sec: int | None = Field(None, ge=10, le=7_200)
    record_calls: bool | None = None

    metadata: dict[str, Any] | None = None

    @field_validator("agent_type")
    @classmethod
    def validate_agent_type(cls, v: str | None) -> str | None:
        if v is not None and v not in AGENT_TYPES:
            raise ValueError(f"agent_type must be one of {sorted(AGENT_TYPES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in AGENT_STATUSES:
            raise ValueError(f"status must be one of {sorted(AGENT_STATUSES)}")
        return v

    @field_validator("noise_removal_level")
    @classmethod
    def validate_noise(cls, v: str | None) -> str | None:
        if v is not None and v not in NOISE_LEVELS:
            raise ValueError(
                f"noise_removal_level must be one of {sorted(NOISE_LEVELS)}"
            )
        return v


class AgentResponse(CamelModel):
    """
    Public agent representation.

    ``system_prompt`` is intentionally **excluded** from this schema —
    prompts are stored securely and never returned in list / detail responses.
    Use ``GET /agents/{agent_id}/prompt`` (requires agent:manage permission)
    to retrieve or edit the prompt.
    """

    id: UUID
    org_id: UUID
    created_by: UUID | None = None
    name: str
    slug: str
    agent_type: str
    status: str

    llm_model: str
    # system_prompt is deliberately absent — security hardening (16.3)
    temperature: float
    max_tokens: int

    language: str | None = None

    tts_voice: str
    tts_speed: float

    vad_threshold: float
    min_speech_ms: int
    silence_ms: int
    allow_interruptions: bool

    noise_removal_level: str

    qdrant_collection: str | None = None
    rag_top_k: int

    tools_json: list[dict[str, Any]] | None = None

    welcome_message: str | None = None
    max_call_duration_sec: int
    record_calls: bool

    metadata: dict[str, Any] = Field(alias="metadata_", default_factory=dict)

    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class AgentListResponse(CamelModel):
    agents: list[AgentResponse]
    pagination: PaginationMeta


# ── Prompt / Tools shortcuts ─────────────────────────────────────────────────

class AgentPromptResponse(CamelModel):
    """
    Returned exclusively by the secure
    ``GET /agents/{agent_id}/prompt`` and
    ``PUT /agents/{agent_id}/prompt`` endpoints.

    Requires agents.agent.manage permission.
    """

    agent_id: UUID
    system_prompt: str | None


class UpdatePromptRequest(CamelModel):
    system_prompt: str = Field(..., min_length=1)


class UpdateToolsRequest(CamelModel):
    tools_json: list[dict[str, Any]] = Field(default_factory=list)


# ── Org secrets (tool-executor credentials) ──────────────────────────────────


class SetOrgSecretRequest(CamelModel):
    """
    Set (or overwrite) one org-level secret used by tool executors.

    ``key`` is substituted as ``{KEY}`` inside a tool's ``executor`` config
    (e.g. a ``dsn_secret_ref`` or an HTTP header template) — never stored in
    ``tools_json`` itself. ``value`` is encrypted at rest and never returned
    by any endpoint once set.
    """

    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=1)


class OrgSecretListResponse(CamelModel):
    """Secret *names* only — values are write-only and never returned."""

    keys: list[str] = Field(default_factory=list)


# ── Test-call response ───────────────────────────────────────────────────────

class TestCallResponse(CamelModel):
    ws_url: str
    session_id: str
    expires_in_seconds: int = 300


# ── WebRTC signalling ─────────────────────────────────────────────────────────

class WebRTCOfferRequest(CamelModel):
    """
    SDP offer forwarded from the browser.

    The browser calls ``RTCPeerConnection.createOffer()``, serialises
    ``localDescription.sdp``, and POSTs it here.  The platform proxies it
    to the pipeline service and returns the answer SDP.
    """
    sdp: str = Field(..., description="SDP offer string")
    type: str = Field(default="offer")


class WebRTCConnectResponse(CamelModel):
    """
    SDP answer and ICE server list returned to the browser.

    Fields
    ------
    sdp:         answer SDP — pass to ``RTCPeerConnection.setRemoteDescription``
    type:        always ``"answer"``
    session_id:  use for subsequent session management REST calls
    ice_servers: list of ``{urls, username?, credential?}`` dicts
    """
    sdp: str
    type: str = "answer"
    session_id: str
    ice_servers: list[dict] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# PHONE NUMBER SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════


class AssignPhoneNumberRequest(CamelModel):
    phone_number: str = Field(
        ...,
        pattern=r"^\+?[1-9]\d{6,29}$",
        description="E.164 or local format, e.g. +14155552671",
    )
    provider: str = Field(default="twilio")
    is_active: bool = True

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v not in PHONE_PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(PHONE_PROVIDERS)}")
        return v


class AgentPhoneNumberResponse(CamelModel):
    id: UUID
    agent_id: UUID
    phone_number: str
    provider: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# CALL LOG SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════


class WriteCallLogRequest(CamelModel):
    """
    Written by the pipeline service after a call ends.
    Only agent_id and org_id are mandatory; everything else is best-effort.
    """

    agent_id: UUID
    org_id: UUID
    session_id: UUID | None = None
    caller_id: str | None = Field(None, max_length=100)
    direction: str = Field(default="inbound")
    transport: str = Field(default="websocket")
    status: str = Field(default="completed")

    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_sec: int | None = Field(None, ge=0)

    transcript: str | None = None
    recording_url: str | None = None
    cost_credits: int | None = Field(None, ge=0)

    stt_ms: int | None = Field(None, ge=0)
    llm_ttft_ms: int | None = Field(None, ge=0)
    tts_ttfb_ms: int | None = Field(None, ge=0)

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in CALL_DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(CALL_DIRECTIONS)}")
        return v

    @field_validator("transport")
    @classmethod
    def validate_transport(cls, v: str) -> str:
        if v not in CALL_TRANSPORTS:
            raise ValueError(f"transport must be one of {sorted(CALL_TRANSPORTS)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in CALL_STATUSES:
            raise ValueError(f"status must be one of {sorted(CALL_STATUSES)}")
        return v


class CallLogResponse(CamelModel):
    id: UUID
    agent_id: UUID
    org_id: UUID
    session_id: UUID | None = None
    caller_id: str | None = None
    direction: str
    transport: str
    status: str

    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_sec: int | None = None

    transcript: str | None = None
    recording_url: str | None = None
    cost_credits: int | None = None

    stt_ms: int | None = None
    llm_ttft_ms: int | None = None
    tts_ttfb_ms: int | None = None

    metadata: dict[str, Any] = Field(alias="metadata_", default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class CallLogListResponse(CamelModel):
    calls: list[CallLogResponse]
    pagination: PaginationMeta


class RecordingUrlResponse(CamelModel):
    url: str
    expires_at: datetime


# ═══════════════════════════════════════════════════════════════════════════
# ANALYTICS SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════


class LatencyStats(CamelModel):
    avg_ms: float | None = None
    p50_ms: float | None = None
    p95_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None


class AgentAnalyticsResponse(CamelModel):
    agent_id: UUID
    period_days: int

    total_calls: int
    completed_calls: int
    failed_calls: int
    success_rate_pct: float | None = None

    avg_duration_sec: float | None = None
    total_duration_sec: int

    stt_latency: LatencyStats
    llm_latency: LatencyStats
    tts_latency: LatencyStats

    inbound_calls: int
    outbound_calls: int


# ═══════════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

KB_DOC_STATUSES = frozenset({"pending", "processing", "completed", "failed"})
KB_FILE_TYPES = frozenset({"pdf", "docx", "txt", "md", "csv", "url", "youtube"})


class KbDocumentResponse(CamelModel):
    """Single knowledge-base document record (ingestion status view)."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: UUID
    agent_id: UUID
    org_id: UUID
    file_name: str
    file_type: str
    file_size_bytes: int | None = None
    source_url: str | None = None
    status: str  # pending | processing | completed | failed
    error_message: str | None = None
    chunk_count: int | None = None
    created_at: datetime
    updated_at: datetime


class KbDocumentListResponse(CamelModel):
    """Paginated list of knowledge-base documents for an agent."""

    documents: list[KbDocumentResponse]
    total: int


class KbUploadResponse(CamelModel):
    """Returned immediately (202) after queuing an ingestion job."""

    doc_id: UUID
    file_name: str
    file_type: str
    status: str = "pending"
    task_id: str
    qdrant_collection: str


class KbDeleteDocResponse(CamelModel):
    """Returned when a document is successfully deleted from the knowledge base."""

    doc_id: UUID
    chunks_deleted: int
    message: str


# ── Usage / quota dashboard ───────────────────────────────────────────────────

class CallMinutesUsageResponse(CamelModel):
    """
    Organisation's AI call-minute consumption for the current calendar month.

    ``allowed_minutes = null`` means the plan has an unlimited quota.
    ``percent_used = null`` when quota is unlimited.
    """

    org_id: UUID
    billing_period: str = Field(
        description="Current billing month in YYYY-MM format."
    )
    used_minutes: int = Field(ge=0, description="Call minutes consumed this month.")
    used_seconds: int = Field(ge=0, description="Raw seconds consumed (for precision).")
    allowed_minutes: int | None = Field(
        default=None,
        description="Monthly minute cap from plan. null = unlimited.",
    )
    remaining_minutes: int | None = Field(
        default=None,
        description="Minutes remaining before cap is hit. null = unlimited.",
    )
    percent_used: float | None = Field(
        default=None,
        description="Percentage of quota consumed (0-100). null = unlimited.",
    )
    plan_feature_key: str = Field(
        default="ai.calls.minutes",
        description="The feature key governing this quota.",
    )


# ── Twilio PSTN / outbound calls ──────────────────────────────────────────────

class OutboundCallRequest(CamelModel):
    """Payload for initiating an outbound PSTN call via Twilio."""

    to_number: str = Field(
        description="Destination phone number in E.164 format (e.g. +15551234567)."
    )
    from_number: str | None = Field(
        default=None,
        description=(
            "Caller-ID override in E.164 format.  When omitted the first phone "
            "number assigned to the agent is used."
        ),
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary key/value pairs forwarded to the pipeline session.",
    )


class OutboundCallResponse(CamelModel):
    """Returned by the outbound-call endpoint once Twilio queues the call."""

    call_sid: str = Field(description="Twilio CallSid for tracking / cancellation.")
    session_id: str = Field(description="Pipeline session ID created for this call.")
    from_number: str = Field(description="Caller-ID used for the outbound call.")
    status: str = Field(
        default="queued",
        description="Initial Twilio call status (typically 'queued').",
    )

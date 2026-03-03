"""
Agents module ORM models.

Tables
------
agents                  — Central config record for every AI voice-bot.
agent_phone_numbers     — Phone numbers assigned to an agent (Twilio / Vonage / own).
call_logs               — Per-call analytics + transcript written on session end.
kb_documents            — Tracks document ingestion status for each agent's knowledge base.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import SoftDeleteMixin, TimestampMixin


# ── Agent ──────────────────────────────────────────────────────────────────


class Agent(Base, TimestampMixin, SoftDeleteMixin):
    """
    Central configuration record for an AI voice-agent.

    Every field the pipeline service needs at runtime is stored here; nothing
    is hard-coded in the pipeline container.
    """

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_agents_org_slug"),
        Index("ix_agents_org_id", "org_id"),
        Index("ix_agents_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Identity ────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="conversational"
    )  # speaker_only | conversational | rag_bot | db_bot
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft"
    )  # draft | active | paused | archived

    # ── LLM Config ──────────────────────────────────────────────────────────
    llm_model: Mapped[str] = mapped_column(
        String(100), nullable=False, default="qwen2.5:3b"
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=512)

    # ── STT Config ──────────────────────────────────────────────────────────
    language: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # NULL = auto-detect

    # ── TTS Config ──────────────────────────────────────────────────────────
    tts_voice: Mapped[str] = mapped_column(
        String(100), nullable=False, default="af_heart"
    )
    tts_speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # ── VAD Config ──────────────────────────────────────────────────────────
    vad_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    min_speech_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=250)
    silence_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    allow_interruptions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # ── Noise Removal ───────────────────────────────────────────────────────
    noise_removal_level: Mapped[str] = mapped_column(
        String(50), nullable=False, default="none"
    )  # none | rnnoise | deepfilternet

    # ── RAG ─────────────────────────────────────────────────────────────────
    qdrant_collection: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # NULL = no KB
    rag_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # ── Function Tools ───────────────────────────────────────────────────────
    tools_json: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )  # OpenAI-format tool definitions array

    # ── Call Config ──────────────────────────────────────────────────────────
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_call_duration_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300
    )
    record_calls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Metadata ─────────────────────────────────────────────────────────────
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    # ── Relationships ────────────────────────────────────────────────────────
    phone_numbers: Mapped[list["AgentPhoneNumber"]] = relationship(
        "AgentPhoneNumber",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    call_logs: Mapped[list["CallLog"]] = relationship(
        "CallLog",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    kb_documents: Mapped[list["KnowledgeBaseDocument"]] = relationship(
        "KnowledgeBaseDocument",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Agent id={self.id} slug={self.slug} org={self.org_id}>"


# ── AgentPhoneNumber ───────────────────────────────────────────────────────


class AgentPhoneNumber(Base):
    """Phone number assigned to an agent."""

    __tablename__ = "agent_phone_numbers"
    __table_args__ = (Index("ix_agent_phone_numbers_agent_id", "agent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    phone_number: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="twilio"
    )  # twilio | vonage | own
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────
    agent: Mapped["Agent"] = relationship(
        "Agent", back_populates="phone_numbers", lazy="noload"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentPhoneNumber {self.phone_number} agent={self.agent_id}>"


# ── CallLog ────────────────────────────────────────────────────────────────


class CallLog(Base):
    """
    Immutable per-call record written by the pipeline service on session end.

    Latency fields (stt_ms / llm_ttft_ms / tts_ttfb_ms) feed the analytics
    endpoint and allow SLA monitoring without querying the Prometheus scrape.
    """

    __tablename__ = "call_logs"
    __table_args__ = (
        Index("ix_call_logs_agent_id", "agent_id"),
        Index("ix_call_logs_org_id", "org_id"),
        Index("ix_call_logs_created_at", "created_at"),
        Index("ix_call_logs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    caller_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # phone number or user_id
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, default="inbound"
    )  # inbound | outbound
    transport: Mapped[str] = mapped_column(
        String(20), nullable=False, default="websocket"
    )  # webrtc | websocket | twilio
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="completed"
    )  # connected | completed | failed | no-answer

    # ── Timing ───────────────────────────────────────────────────────────
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Content ──────────────────────────────────────────────────────────
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Latency metrics ──────────────────────────────────────────────────
    stt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tts_ttfb_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Metadata ─────────────────────────────────────────────────────────
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────
    agent: Mapped["Agent"] = relationship(
        "Agent", back_populates="call_logs", lazy="noload"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CallLog id={self.id} agent={self.agent_id} status={self.status}>"


# ── KnowledgeBaseDocument ──────────────────────────────────────────────────


class KnowledgeBaseDocument(Base):
    """
    Tracks the ingestion lifecycle of a document added to an agent's
    knowledge base (Qdrant collection).

    A single upload may produce many Qdrant point vectors (one per chunk);
    this row stores metadata about the source document so the API can list
    and delete them by document rather than by individual vector.

    Ingestion status lifecycle:
        pending → processing → completed
                             → failed

    Deleting a document record also triggers removal of all Qdrant points
    whose ``doc_id`` payload field matches this row's ``id``.
    """

    __tablename__ = "kb_documents"
    __table_args__ = (
        Index("ix_kb_documents_agent_id", "agent_id"),
        Index("ix_kb_documents_org_id", "org_id"),
        Index("ix_kb_documents_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Source info ──────────────────────────────────────────────────────
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # pdf | docx | txt | md | csv | url | youtube
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Ingestion state ──────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending | processing | completed | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Timestamps ───────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────────
    agent: Mapped["Agent"] = relationship(
        "Agent", back_populates="kb_documents", lazy="noload"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<KnowledgeBaseDocument id={self.id}"
            f" file={self.file_name} status={self.status}>"
        )

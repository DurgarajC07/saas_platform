"""
Dashboard module — Pydantic response schemas.

All schemas use camelCase JSON keys via CamelModel.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.shared.base_schemas import CamelModel


# ── Overview ──────────────────────────────────────────────────────────────────

class TopAgentRow(CamelModel):
    agent_id: UUID
    agent_name: str
    total_calls: int
    success_rate: float = Field(ge=0.0, le=100.0)
    avg_duration_sec: float | None = None


class OverviewResponse(CamelModel):
    """
    Real-time snapshot for the dashboard home card.

    ``active_calls`` is taken from the Redis ``active_calls:{org_id}`` counter
    maintained by the pipeline service.  All other figures cover the current
    calendar month.
    """

    period: str = Field(description="Billing period in YYYY-MM format.")
    active_calls: int = Field(ge=0, description="Live calls right now.")
    total_calls_this_month: int = Field(ge=0)
    completed_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=100.0, description="Percentage of completed calls.")
    total_minutes_used: int = Field(ge=0, description="Call minutes consumed this month.")
    top_agents: list[TopAgentRow] = Field(
        default_factory=list,
        description="Up to five agents ranked by call volume.",
    )
    generated_at: datetime


# ── Latency ───────────────────────────────────────────────────────────────────

class LatencyBucket(CamelModel):
    """One time-bucket (1-hour or 1-day) of latency percentiles."""

    label: str = Field(description="ISO-8601 bucket start time.")
    sample_count: int = Field(ge=0)
    p50_stt_ms: float | None = None
    p95_stt_ms: float | None = None
    p99_stt_ms: float | None = None
    p50_llm_ms: float | None = None
    p95_llm_ms: float | None = None
    p99_llm_ms: float | None = None
    p50_tts_ms: float | None = None
    p95_tts_ms: float | None = None
    p99_tts_ms: float | None = None


class LatencySummary(CamelModel):
    """Aggregate over the whole window."""

    p50_stt_ms: float | None = None
    p95_stt_ms: float | None = None
    p99_stt_ms: float | None = None
    p50_llm_ms: float | None = None
    p95_llm_ms: float | None = None
    p99_llm_ms: float | None = None
    p50_tts_ms: float | None = None
    p95_tts_ms: float | None = None
    p99_tts_ms: float | None = None


class LatencyResponse(CamelModel):
    """24-hour latency profile consumed by dashboard latency chart."""

    window_hours: int = 24
    buckets: list[LatencyBucket]
    summary: LatencySummary
    generated_at: datetime


# ── Call volume ───────────────────────────────────────────────────────────────

class CallVolumePoint(CamelModel):
    label: str = Field(description="Hour/day/month label for the x-axis.")
    total_calls: int = Field(ge=0)
    completed_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    total_duration_sec: int = Field(ge=0)
    inbound_calls: int = Field(ge=0)
    outbound_calls: int = Field(ge=0)


class CallVolumeResponse(CamelModel):
    granularity: Literal["hour", "day", "month"]
    points: list[CallVolumePoint]
    total_calls: int = Field(ge=0)
    total_duration_sec: int = Field(ge=0)
    generated_at: datetime


# ── Agent performance ─────────────────────────────────────────────────────────

class AgentPerformanceRow(CamelModel):
    agent_id: UUID
    agent_name: str
    total_calls: int = Field(ge=0)
    completed_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=100.0)
    avg_duration_sec: float | None = None
    avg_stt_ms: float | None = None
    avg_llm_ms: float | None = None
    avg_tts_ms: float | None = None


class AgentPerformanceResponse(CamelModel):
    agents: list[AgentPerformanceRow]
    period_days: int
    generated_at: datetime


# ── Agent deep-dive analytics ─────────────────────────────────────────────────

class TranscriptSample(CamelModel):
    call_id: UUID
    started_at: datetime | None
    duration_sec: int | None
    transcript_snippet: str | None = Field(
        default=None, description="First 200 chars of the transcript."
    )


class AgentDeepDiveResponse(CamelModel):
    agent_id: UUID
    period_days: int
    total_calls: int
    completed_calls: int
    failed_calls: int
    success_rate: float
    avg_duration_sec: float | None
    # Latency breakdowns
    p50_stt_ms: float | None = None
    p95_stt_ms: float | None = None
    p99_stt_ms: float | None = None
    p50_llm_ms: float | None = None
    p95_llm_ms: float | None = None
    p99_llm_ms: float | None = None
    p50_tts_ms: float | None = None
    p95_tts_ms: float | None = None
    p99_tts_ms: float | None = None
    recent_samples: list[TranscriptSample] = Field(default_factory=list)
    generated_at: datetime


# ── Admin — GPU status ────────────────────────────────────────────────────────

class GPUDeviceInfo(CamelModel):
    index: int
    name: str
    vram_total_mib: int
    vram_used_mib: int
    vram_free_mib: int
    vram_utilization_pct: float
    gpu_utilization_pct: float
    temperature_celsius: float
    power_draw_watts: float | None = None
    power_limit_watts: float | None = None


class GPUStatusResponse(CamelModel):
    nvml_available: bool
    driver_version: str | None = None
    cuda_version: str | None = None
    devices: list[GPUDeviceInfo] = Field(default_factory=list)
    generated_at: datetime


# ── Admin — Queue status ──────────────────────────────────────────────────────

class QueueInfo(CamelModel):
    name: str
    pending: int = Field(ge=0)
    active: int = Field(ge=0)
    reserved: int = Field(ge=0)
    failed: int = Field(ge=0)


class QueueStatusResponse(CamelModel):
    queues: list[QueueInfo]
    workers_online: int = Field(ge=0)
    generated_at: datetime


# ── Admin — Model benchmark ───────────────────────────────────────────────────

class ModelBenchmarkRequest(CamelModel):
    model_name: str = Field(description="Model slug to benchmark (e.g. whisper-large-v3).")
    sample_text: str = Field(
        default="The quick brown fox jumps over the lazy dog.",
        description="Text used for TTS/LLM inference; audio for STT.",
    )
    runs: int = Field(default=3, ge=1, le=10)


class ModelBenchmarkResult(CamelModel):
    model_name: str
    runs: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    error: str | None = None


class ModelBenchmarkResponse(CamelModel):
    results: list[ModelBenchmarkResult]
    benchmark_at: datetime

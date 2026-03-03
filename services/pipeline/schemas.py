"""
Pipeline Service — Shared Pydantic schemas.

AgentConfig mirrors the database row that will be fetched by the FastAPI
platform (app/modules/agents/) on Day 4.  The pipeline service receives it
as JSON over the REST call that creates a session, so it never touches the DB
directly.

AgentType values
----------------
speaker_only       — plays pre-scripted audio, no STT/LLM
conversational     — full STT → LLM → TTS loop (default)
rag_bot            — conversational + Qdrant RAG retrieval
tool_bot           — conversational + function/API tool execution
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from string import Formatter
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentType(str, Enum):
    SPEAKER_ONLY   = "speaker_only"
    CONVERSATIONAL = "conversational"
    RAG_BOT        = "rag_bot"
    TOOL_BOT       = "tool_bot"


class NoiseRemovalLevel(str, Enum):
    """
    Two-stage noise removal level.

    none          — raw audio forwarded unchanged (lowest latency)
    rnnoise       — Stage 1: RNNoise RNN denoiser, < 1 ms/frame (default)
    deepfilternet — Stage 1 + Stage 2: RNNoise + DeepFilterNet3 (best quality,
                    adds ~5 ms; recommended for call-centre / outdoor agents)
    """
    NONE          = "none"
    RNNOISE       = "rnnoise"
    DEEPFILTERNET = "deepfilternet"


# ── Language → TTS voice mapping ──────────────────────────────────────────────
# BCP-47 language code returned by Whisper auto-detection → Kokoro voice id.
# Used by SessionManager to switch voices mid-session when the caller's
# language differs from the agent's configured default.
LANGUAGE_VOICE_MAP: dict[str, str] = {
    "en": "af_heart",    # English (American)
    "hi": "hf_alpha",    # Hindi
    "es": "ef_dora",     # Spanish
    "fr": "ff_siwis",    # French
    "de": "df_ketola",   # German
    "ja": "jf_alpha",    # Japanese
    "zh": "zf_xiaobei",  # Mandarin
    "ko": "kf_luna",     # Korean
    "pt": "pf_dora",     # Portuguese
}



# -- Prompt template helpers ---------------------------------------------------

class PromptContext(BaseModel):
    """
    Runtime variables resolved into the agent's system prompt template.

    Each field maps to a {placeholder} in the prompt text. Unknown
    placeholders are left unchanged (safe substitution).

    Example template usage
    ----------------------
    "You are {agent_name}, an assistant for {org_name}. Today is {today}.
    Respond in {language}. Keep answers under {max_words} words."
    """
    agent_name:          str = "Assistant"
    org_name:            str = "the organization"
    caller_name:         str = "the caller"
    language:            str = "English"
    max_words:           int = 150
    today:               str = Field(default_factory=lambda: date.today().isoformat())
    pricing_response:    str = ""
    custom_instructions: str = ""


def resolve_system_prompt(template: str, ctx: "PromptContext | None" = None) -> str:
    """
    Substitute {variable} placeholders in *template* using *ctx*.

    Safe: placeholders with no matching PromptContext field are kept verbatim.

    Parameters
    ----------
    template : str
        Raw system prompt text, possibly containing {placeholder} tokens.
    ctx : PromptContext | None
        Variable values; if None the template is returned unchanged.

    Returns
    -------
    str
        Resolved system prompt string.
    """
    if ctx is None:
        return template

    values = ctx.model_dump()

    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(_SafeDict(values))


class AgentConfig(BaseModel):
    """
    Full agent configuration loaded from the saas_platform database.

    All values here map 1-to-1 with the ``agents`` table columns that
    will be created on Day 4 via Alembic migration.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    agent_id: str
    organization_id: str
    name: str
    agent_type: AgentType = AgentType.CONVERSATIONAL

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_model: str          = Field(default="qwen2.5:3b")
    system_prompt: str      = Field(default="You are a helpful voice assistant.")
    temperature: float      = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int         = Field(default=512,  ge=1, le=4096)
    tools_json: list[dict[str, Any]] | None = None  # OpenAI-compatible tool defs
    max_turns: int                              = Field(default=20, ge=1, le=100)
    prompt_context: PromptContext | None        = None   # Template vars resolved at call start

    # ── STT ───────────────────────────────────────────────────────────────────
    language: str | None    = None        # None = auto-detect
    whisper_url: str        = Field(default="ws://whisper-1:9000/transcribe/stream")

    # ── TTS ───────────────────────────────────────────────────────────────────
    tts_voice: str          = Field(default="af_heart")
    tts_speed: float        = Field(default=1.0, ge=0.25, le=3.0)
    tts_lang: str           = Field(default="a")
    kokoro_url: str         = Field(default="ws://kokoro-1:8880/tts/stream")

    # ── VAD ───────────────────────────────────────────────────────────────────
    vad_threshold: float    = Field(default=0.5, ge=0.1, le=0.95)
    min_speech_ms: int      = Field(default=250, ge=50)
    silence_ms: int         = Field(default=800, ge=200)

    # ── RAG ───────────────────────────────────────────────────────────────────
    qdrant_collection: str | None = None
    rag_top_k: int          = Field(default=3, ge=1, le=10)
    qdrant_url: str         = Field(default="http://qdrant:6333")

    # ── Noise removal ─────────────────────────────────────────────────────────
    noise_removal_level: NoiseRemovalLevel = NoiseRemovalLevel.RNNOISE

    # ── Interruption / barge-in ───────────────────────────────────────────────
    allow_interruptions: bool    = True
    barge_in_threshold: float    = Field(default=0.3, ge=0.0, le=1.0)

    @field_validator("agent_type", mode="before")
    @classmethod
    def coerce_agent_type(cls, v: str | AgentType) -> AgentType:
        if isinstance(v, AgentType):
            return v
        return AgentType(v)


class SessionCreateRequest(BaseModel):
    """Request body for POST /sessions — starts a new call session."""
    agent_config: AgentConfig
    call_id: str | None     = None   # external telephony call ID
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionInfo(BaseModel):
    """Response body for POST /sessions and GET /sessions/{session_id}."""
    session_id: str
    agent_id: str
    call_id: str | None
    status: str              # "created" | "running" | "ended" | "error"
    ws_url: str              # WebSocket URL for the caller to connect to
    created_at: str


class HealthResponse(BaseModel):
    status: str
    sessions_active: int
    version: str = "1.0.0"

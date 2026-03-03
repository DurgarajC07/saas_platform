"""
Pipeline Service — FastAPI entry point.

Endpoints
---------
POST /sessions                Create a new call session (returns WS URL + session_id)
GET  /sessions/{session_id}   Get session status and metadata
DELETE /sessions/{session_id} End a running session (graceful shutdown)
WS   /sessions/{session_id}/ws  WebSocket: raw PCM in → PCM audio out (loopback transport)
GET  /health                  Liveness probe
GET  /info                    Build / runtime metadata

Architecture
------------
Each POST /sessions allocates a PipelineSession backed by a Pipecat Pipeline.
When the caller connects on /sessions/{id}/ws, the session starts pumping frames.
Concurrent sessions share a single uvicorn worker via asyncio — no threading.

Env vars
--------
HOST_WHISPER_URL   whisper WebSocket URL   (default: ws://whisper-1:9000/transcribe/stream)
HOST_KOKORO_URL    kokoro  WebSocket URL   (default: ws://kokoro-1:8880/tts/stream)
HOST_QDRANT_URL    qdrant  REST URL        (default: http://qdrant:6333)
HOST_OLLAMA_URL    ollama  base URL        (default: http://host.docker.internal:11434)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

from schemas import AgentConfig, HealthResponse, SessionCreateRequest, SessionInfo, WebRTCAnswerResponse, WebRTCOfferRequest
from session_manager import SessionManager
from metrics import init_metrics, get_metrics
from transports.webrtc import ice_servers_for_client

logger = structlog.get_logger(__name__)

# ── Session manager singleton ─────────────────────────────────────────────────

_session_manager: SessionManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _session_manager
    logger.info("pipeline.startup")
    _session_manager = SessionManager()
    await _session_manager.startup()
    init_metrics(max_concurrent_calls=SessionManager.MAX_CONCURRENT_CALLS)
    logger.info("pipeline.ready")
    yield
    logger.info("pipeline.shutdown")
    if _session_manager:
        await _session_manager.shutdown()
    _session_manager = None
    logger.info("pipeline.stopped")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Pipeline Service",
    version="1.0.0",
    description="AI Voice Call Engine — Pipecat-powered STT → LLM → TTS pipeline",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


# ── Health / Info ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"], response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe — always 200 once startup completes."""
    active = _session_manager.active_count() if _session_manager else 0
    return HealthResponse(status="ok", sessions_active=active)


@app.get("/metrics", tags=["System"], summary="Pipeline latency and capacity metrics")
async def pipeline_metrics() -> dict:
    """
    Return a real-time snapshot of pipeline performance.

    Fields
    ------
    sessions_active        — number of live WS sessions right now
    max_concurrent_calls   — hard cap (``SessionManager.MAX_CONCURRENT_CALLS``)
    avg_vad_ms             — rolling average VAD inference time per audio frame
    avg_stt_ms             — rolling average STT round-trip (audio upload → transcript)
    avg_llm_ttft_ms        — rolling average LLM time-to-first-token
    avg_tts_ttfb_ms        — rolling average TTS first-audio latency
    avg_e2e_ms             — rolling average end-to-end session duration
    p95_e2e_ms             — p95 end-to-end latency over the last 50 calls
    gpu_utilization_pct    — GPU core utilization on device 0 (None if unavailable)
    total_calls_served     — lifetime calls since process start
    uptime_s               — seconds since process started
    """
    m = get_metrics()
    if m is None:
        raise HTTPException(status_code=503, detail="Metrics not available")
    return m.snapshot().to_dict()


@app.get("/info", tags=["System"])
async def info() -> dict:
    return {
        "service": "pipeline",
        "version": "1.0.0",
        "whisper_url": os.getenv("HOST_WHISPER_URL", "ws://whisper-1:9000/transcribe/stream"),
        "kokoro_url":  os.getenv("HOST_KOKORO_URL",  "ws://kokoro-1:8880/tts/stream"),
        "qdrant_url":  os.getenv("HOST_QDRANT_URL",  "http://qdrant:6333"),
        "ollama_url":  os.getenv("HOST_OLLAMA_URL",  "http://host.docker.internal:11434"),
        "sessions_active": _session_manager.active_count() if _session_manager else 0,
    }


# ── Session REST API ──────────────────────────────────────────────────────────

@app.post(
    "/sessions",
    tags=["Sessions"],
    status_code=status.HTTP_201_CREATED,
    response_model=SessionInfo,
    summary="Create a new call session",
)
async def create_session(body: SessionCreateRequest) -> SessionInfo:
    """
    Allocate a PipelineSession and return its WebSocket URL.

    The caller should:
      1. POST /sessions with the agent config.
      2a. (WebSocket) Connect to the returned ``ws_url`` with raw 16-bit PCM audio at 16 kHz.
      2b. (WebRTC)    POST an SDP offer to ``webrtc_url`` to get an SDP answer, then
          connect via standard ``RTCPeerConnection``.
      3. Receive binary frames containing 16-bit PCM audio responses.
      4. DELETE /sessions/{id} when the call ends (or let it timeout).
    """
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Session manager not ready")

    # Determine base URL for session endpoint URLs
    base_http = os.getenv("PIPELINE_BASE_URL", "http://localhost:7000")
    base_ws   = base_http.replace("https://", "wss://").replace("http://", "ws://")

    session = await _session_manager.create(
        agent_config=body.agent_config,
        call_id=body.call_id,
        metadata=body.metadata,
        base_url=base_ws,
    )
    # Populate WebRTC offer URL so clients know where to send the SDP offer
    session.webrtc_url = f"{base_http}/sessions/{session.session_id}/webrtc/offer"
    return session


@app.get(
    "/sessions/{session_id}",
    tags=["Sessions"],
    response_model=SessionInfo,
    summary="Get session status",
)
async def get_session(session_id: str) -> SessionInfo:
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Session manager not ready")
    session = _session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return session


@app.delete(
    "/sessions/{session_id}",
    tags=["Sessions"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End a running session",
)
async def end_session(session_id: str) -> None:
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Session manager not ready")
    ok = await _session_manager.end(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")


# ── WebSocket transport ───────────────────────────────────────────────────────

@app.websocket("/sessions/{session_id}/ws")
async def session_ws(session_id: str, ws: WebSocket) -> None:
    """
    WebSocket for a running call session.

    Binary protocol
    ---------------
    Client → Server : raw int16 PCM bytes at 16 kHz mono, streaming audio chunks
    Server → Client : raw int16 PCM bytes at 24 kHz mono, TTS audio response
    Server → Client : JSON text frame ``{"event": "transcript", "text": "..."}``
    Server → Client : JSON text frame ``{"event": "llm_chunk",  "text": "..."}``
    Server → Client : JSON text frame ``{"event": "end"}`` when pipeline finishes
    """
    if not _session_manager:
        await ws.close(code=1011, reason="session manager not ready")
        return

    session = _session_manager.get(session_id)
    if not session:
        await ws.close(code=4404, reason=f"session {session_id!r} not found")
        return

    # Accept the WebSocket upgrade here so the client gets HTTP 101
    # immediately.  pipecat's FastAPIWebsocketTransport does NOT call
    # ws.accept() itself; without this the client's opening handshake
    # never completes and it times out.
    await ws.accept()

    log = logger.bind(session_id=session_id)
    log.info("pipeline.ws_connected")
    try:
        await _session_manager.run_ws(session_id, ws)
    except WebSocketDisconnect:
        log.info("pipeline.ws_disconnected")
    except Exception as exc:
        log.exception("pipeline.ws_error", error=str(exc))
    finally:
        log.info("pipeline.ws_closed")


# ── WebRTC signalling ─────────────────────────────────────────────────────────

@app.post(
    "/sessions/{session_id}/webrtc/offer",
    tags=["Sessions"],
    response_model=WebRTCAnswerResponse,
    summary="WebRTC SDP offer → answer exchange",
)
async def webrtc_offer(
    session_id: str, body: WebRTCOfferRequest
) -> WebRTCAnswerResponse:
    """
    Accept an SDP offer from a browser ``RTCPeerConnection``, perform the
    ICE-gathering / DTLS handshake via aiortc, and return the SDP answer.

    The browser flow is:
      1. ``POST /sessions`` to create a session.
      2. ``POST /sessions/{id}/webrtc/offer`` with ``{sdp, type}`` payload.
      3. Set the returned ``sdp`` as the remote description on the
         ``RTCPeerConnection``.
      4. Audio now flows bidirectionally over SRTP.

    A ``409 Conflict`` is returned when the session already has an active
    WebRTC connection.  A ``404`` is returned for unknown sessions.
    """
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Session manager not ready")
    session = _session_manager.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404, detail=f"Session {session_id!r} not found"
        )
    result = await _session_manager.setup_webrtc(
        session_id, body.sdp, body.type
    )
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="WebRTC already configured for this session or session not found",
        )
    answer_sdp, answer_type = result
    return WebRTCAnswerResponse(
        sdp=answer_sdp,
        type=answer_type,
        session_id=session_id,
        ice_servers=ice_servers_for_client(),
    )

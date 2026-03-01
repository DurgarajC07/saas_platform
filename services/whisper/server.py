"""
Whisper STT Service — faster-whisper Large-V3-Turbo.

Wraps faster-whisper with a FastAPI HTTP interface.
Designed to be called by the Pipecat pipeline during live calls —
audio chunk in, transcript out, low latency.

Endpoints
---------
POST /transcribe     Blocking: audio file → full transcript + segments
POST /transcribe/vad Transcribe with aggressive Silero VAD pre-filter
GET  /info           Model metadata
GET  /health         Liveness probe (ready only after model is loaded)

Env vars
--------
MODEL           faster-whisper model name          (default: large-v3-turbo)
DEVICE          cuda | cpu                         (default: cuda)
COMPUTE_TYPE    float16 | int8_float16 | int8      (default: float16)
NUM_WORKERS     CTranslate2 inter-op threads        (default: 2)

Notes
-----
* `workers=1` in uvicorn — GPU memory is not shareable between processes.
  Scale horizontally by running multiple containers (whisper-1, whisper-2).
* The model is downloaded on first startup to /app/models (volume-mounted).
  Subsequent startups are instant from cache (~3s warm-up).
* Audio formats accepted: wav, mp3, ogg, flac, webm, m4a, mp4, opus — any
  container ffmpeg can decode.
"""

from __future__ import annotations

import io
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_MODEL_NAME: str = os.getenv("MODEL", "large-v3-turbo")
_DEVICE: str = os.getenv("DEVICE", "cuda")
_COMPUTE_TYPE: str = os.getenv("COMPUTE_TYPE", "float16")
_NUM_WORKERS: int = int(os.getenv("NUM_WORKERS", "2"))
_CACHE_DIR: str = os.getenv("WHISPER_CACHE", "/app/models")

# ── Model singleton ───────────────────────────────────────────────────────────

_model: WhisperModel | None = None
_startup_ts: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _startup_ts

    logger.info(
        "whisper.loading",
        model=_MODEL_NAME,
        device=_DEVICE,
        compute_type=_COMPUTE_TYPE,
        num_workers=_NUM_WORKERS,
    )
    t0 = time.perf_counter()

    # CTranslate2 / faster-whisper download + load
    _model = WhisperModel(
        _MODEL_NAME,
        device=_DEVICE,
        compute_type=_COMPUTE_TYPE,
        num_workers=_NUM_WORKERS,
        download_root=_CACHE_DIR,
        local_files_only=False,   # download if not cached
    )

    _startup_ts = time.perf_counter() - t0
    logger.info(
        "whisper.ready",
        model=_MODEL_NAME,
        device=_DEVICE,
        load_s=round(_startup_ts, 2),
    )
    yield
    # Cleanup: release GPU memory
    _model = None
    logger.info("whisper.shutdown")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Whisper STT",
    version="1.0.0",
    description="faster-whisper Large-V3-Turbo transcription service",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


# ── Health / Info ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health() -> dict:
    """Liveness probe — returns 503 until model is fully loaded."""
    if _model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model not yet loaded",
        )
    return {"status": "ok", "model": _MODEL_NAME, "device": _DEVICE}


@app.get("/info", tags=["System"])
async def info() -> dict:
    """Return model configuration and startup metadata."""
    return {
        "model": _MODEL_NAME,
        "device": _DEVICE,
        "compute_type": _COMPUTE_TYPE,
        "num_workers": _NUM_WORKERS,
        "ready": _model is not None,
        "load_s": round(_startup_ts, 2),
    }


# ── Transcription ─────────────────────────────────────────────────────────────

async def _run_transcription(
    audio_bytes: bytes,
    *,
    language: str | None,
    task: str,
    beam_size: int,
    word_timestamps: bool,
    vad_filter: bool,
    min_silence_ms: int = 500,
) -> JSONResponse:
    """Shared transcription logic used by both endpoints."""
    if _model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model not yet loaded",
        )

    audio_stream = io.BytesIO(audio_bytes)
    t0 = time.perf_counter()

    try:
        segments_iter, info = _model.transcribe(
            audio_stream,
            language=language or None,
            task=task,
            beam_size=beam_size,
            word_timestamps=word_timestamps,
            vad_filter=vad_filter,
            vad_parameters={"min_silence_duration_ms": min_silence_ms},
            condition_on_previous_text=True,
            log_prob_threshold=-1.0,   # keep all segments
            no_speech_threshold=0.6,
        )

        # Fully materialise the lazy generator (faster-whisper is synchronous)
        segments: list[dict] = []
        for seg in segments_iter:
            entry: dict = {
                "id": seg.id,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "avg_logprob": round(seg.avg_logprob, 4),
                "no_speech_prob": round(seg.no_speech_prob, 4),
            }
            if word_timestamps and seg.words:
                entry["words"] = [
                    {
                        "word": w.word,
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "probability": round(w.probability, 3),
                    }
                    for w in seg.words
                ]
            segments.append(entry)

    except Exception as exc:
        logger.exception("whisper.transcribe_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {exc}",
        ) from exc

    full_text = " ".join(s["text"] for s in segments if s["text"]).strip()
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    audio_duration_s = round(info.duration, 2)
    rtf = round(elapsed_ms / 1000 / max(audio_duration_s, 0.001), 3)  # real-time factor

    logger.info(
        "whisper.transcribed",
        language=info.language,
        lang_prob=round(info.language_probability, 3),
        audio_s=audio_duration_s,
        elapsed_ms=elapsed_ms,
        rtf=rtf,
        segments=len(segments),
        chars=len(full_text),
    )

    return JSONResponse({
        "text": full_text,
        "language": info.language,
        "language_probability": round(info.language_probability, 4),
        "duration_s": audio_duration_s,
        "elapsed_ms": elapsed_ms,
        "real_time_factor": rtf,
        "task": task,
        "segments": segments,
    })


@app.post(
    "/transcribe",
    tags=["Transcription"],
    summary="Transcribe audio file",
    response_description="Transcript with segments and timing",
)
async def transcribe(
    file: Annotated[UploadFile, File(description="Audio file — wav, mp3, ogg, flac, webm, m4a, opus")],
    language: str = Form(
        default=None,
        description="BCP-47 language code (e.g. 'en', 'hi', 'de'). "
                    "Omit to auto-detect.",
    ),
    task: str = Form(
        default="transcribe",
        description="transcribe (keep original language) | translate (to English)",
    ),
    beam_size: int = Form(default=5, ge=1, le=10),
    word_timestamps: bool = Form(
        default=False,
        description="Include per-word start/end times and probabilities",
    ),
    vad_filter: bool = Form(
        default=True,
        description="Apply Silero VAD filter to strip non-speech segments "
                    "before transcription — reduces hallucinations",
    ),
) -> JSONResponse:
    """
    Transcribe an uploaded audio file.

    Accepts any format ffmpeg can decode.  Returns the full text, per-segment
    timing, detected language and a real-time-factor metric.
    """
    audio_bytes = await file.read()
    return await _run_transcription(
        audio_bytes,
        language=language,
        task=task,
        beam_size=beam_size,
        word_timestamps=word_timestamps,
        vad_filter=vad_filter,
    )


@app.post(
    "/transcribe/vad",
    tags=["Transcription"],
    summary="Transcribe with aggressive VAD (call audio optimised)",
)
async def transcribe_vad(
    file: Annotated[UploadFile, File()],
    language: str = Form(default=None),
    task: str = Form(default="transcribe"),
    beam_size: int = Form(default=5, ge=1, le=10),
    word_timestamps: bool = Form(default=False),
    min_silence_ms: int = Form(
        default=300,
        description="Minimum silence duration in ms before splitting — "
                    "300ms works well for phone call audio",
    ),
) -> JSONResponse:
    """
    Transcription endpoint tuned for phone call / WebRTC audio.

    Uses a tighter VAD silence threshold (300ms) which gives better
    segmentation on conversational speech with short pauses.
    """
    audio_bytes = await file.read()
    return await _run_transcription(
        audio_bytes,
        language=language,
        task=task,
        beam_size=beam_size,
        word_timestamps=word_timestamps,
        vad_filter=True,
        min_silence_ms=min_silence_ms,
    )

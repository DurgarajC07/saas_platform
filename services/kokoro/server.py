"""
Kokoro TTS Service — Kokoro-82M neural text-to-speech.

Wraps the ``kokoro`` Python package with a FastAPI HTTP interface.
Designed to be called by the Pipecat pipeline — text chunk in, PCM/WAV out.

Endpoints
---------
POST /tts              Text → WAV audio bytes (blocking, full utterance)
POST /tts/stream       Text → chunked WAV stream (sentence-by-sentence)
GET  /voices           List available voices grouped by language
GET  /info             Runtime configuration
GET  /health           Liveness probe

Request body (JSON)
-------------------
{
  "text":    "Hello, how can I help you?",
  "voice":   "af_heart",    // optional, default: env DEFAULT_VOICE
  "speed":   1.0,           // float 0.5–2.0
  "lang":    "a"            // Kokoro lang_code
}

Output
------
Content-Type: audio/wav  — 16-bit PCM WAV at 24 000 Hz, mono channel.

Voices reference
----------------
American English ('a'):  af_heart, af_bella, af_nicole, af_sarah, af_sky
                         am_adam, am_michael, am_fenrir, am_liam, am_puck
British English  ('b'):  bf_emma, bf_isabella, bm_george, bm_lewis
Hindi            ('hi'): hf_alpha, hf_beta, hm_omega, hm_psi
Spanish          ('es'): ef_daria, em_alex, em_santa
French           ('fr'): ff_siwis
Italian          ('it'): if_sara, im_nicola
Japanese         ('ja'): jf_alpha, jf_gongitsune, jm_kumo
Korean           ('ko'): kf_alpha, km_hyun
Portuguese       ('pt'): pf_dora, pm_alex
Chinese          ('zh'): zf_xiaobei, zf_xiaoni, zm_yunjian

Sample rate
-----------
Kokoro outputs 24 000 Hz float32 mono.  We encode to WAV for maximum
compatibility with pipecat / WebRTC bridges that consume this service.

Notes
-----
* One KPipeline is instantiated per lang_code. Idle pipelines stay loaded;
  the dict is a small per-language singleton cache.
* uvicorn runs 2 worker processes — Kokoro is stateless after model load,
  so multiprocessing works fine on CPU. On GPU use workers=1.
"""

from __future__ import annotations

import io
import os
import struct
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

import numpy as np
import soundfile as sf
import structlog
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_DEFAULT_VOICE: str = os.getenv("DEFAULT_VOICE", "af_heart")
_DEFAULT_SPEED: float = float(os.getenv("DEFAULT_SPEED", "1.0"))
_DEFAULT_LANG: str = os.getenv("DEFAULT_LANG", "a")
_SAMPLE_RATE: int = 24_000  # Kokoro fixed output sample rate

# ── Pipeline cache ────────────────────────────────────────────────────────────
# Dict[lang_code → KPipeline].  Built lazily on first request per language.
_pipelines: dict[str, Any] = {}
_startup_ts: float = 0.0


def _get_pipeline(lang_code: str) -> Any:
    """
    Return the cached KPipeline for *lang_code*, loading it on first use.

    Raises ValueError for unsupported lang codes.
    """
    global _pipelines
    if lang_code not in _pipelines:
        try:
            from kokoro import KPipeline  # import here to fail loudly during boot

            logger.info("kokoro.pipeline_init", lang=lang_code)
            t0 = time.perf_counter()
            _pipelines[lang_code] = KPipeline(lang_code=lang_code)
            logger.info(
                "kokoro.pipeline_ready",
                lang=lang_code,
                load_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:
            raise ValueError(f"Failed to load Kokoro pipeline for lang '{lang_code}': {exc}") from exc
    return _pipelines[lang_code]


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_ts
    t0 = time.perf_counter()
    logger.info("kokoro.startup: warming default pipeline", lang=_DEFAULT_LANG)
    try:
        _get_pipeline(_DEFAULT_LANG)  # warm up default language on startup
    except Exception as exc:
        logger.error("kokoro.startup_failed", error=str(exc))
        # Don't crash — allow the container to start; /health will report not ready
    _startup_ts = time.perf_counter() - t0
    logger.info("kokoro.ready", load_s=round(_startup_ts, 2))
    yield
    _pipelines.clear()
    logger.info("kokoro.shutdown")


# ── Schema ────────────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Text to synthesise. Long texts are split by Kokoro's "
                    "sentence chunker automatically.",
    )
    voice: str = Field(
        default_factory=lambda: _DEFAULT_VOICE,
        description="Voice identifier, e.g. 'af_heart'. See /voices for list.",
    )
    speed: float = Field(
        default_factory=lambda: _DEFAULT_SPEED,
        ge=0.25,
        le=3.0,
        description="Speech rate multiplier.  1.0 = normal speed.",
    )
    lang: str = Field(
        default_factory=lambda: _DEFAULT_LANG,
        description="Kokoro lang_code: 'a'=American EN, 'b'=British EN, "
                    "'hi'=Hindi, 'es'=Spanish, 'fr'=French, 'it'=Italian, "
                    "'ja'=Japanese, 'ko'=Korean, 'pt'=Portuguese, 'zh'=Chinese",
    )

    @field_validator("text")
    @classmethod
    def strip_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty after stripping")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────

def _numpy_to_wav(audio: np.ndarray, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """
    Encode a float32 numpy array to a 16-bit PCM WAV byte string.

    We clip to [-1, 1] before converting to avoid integer overflow artefacts.
    """
    buf = io.BytesIO()
    # soundfile writes standard WAV — handles the RIFF header and PCM encoding
    sf.write(buf, audio, sample_rate, subtype="PCM_16", format="WAV")
    buf.seek(0)
    return buf.read()


def _synthesise(req: TTSRequest) -> tuple[bytes, float, float]:
    """
    Run Kokoro synthesis synchronously.

    Returns
    -------
    wav_bytes : bytes — full WAV file
    duration_s : float — audio duration in seconds
    elapsed_ms : float — wall-clock synthesis time in milliseconds
    """
    pipeline = _get_pipeline(req.lang)

    t0 = time.perf_counter()
    chunks: list[np.ndarray] = []

    generator = pipeline(req.text, voice=req.voice, speed=req.speed)
    for _graphemes, _phonemes, audio_chunk in generator:
        if audio_chunk is not None and len(audio_chunk) > 0:
            chunks.append(audio_chunk)

    if not chunks:
        raise ValueError("Kokoro returned empty audio for the given text")

    audio = np.concatenate(chunks).astype(np.float32)
    audio = np.clip(audio, -1.0, 1.0)

    wav_bytes = _numpy_to_wav(audio)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    duration_s = round(len(audio) / _SAMPLE_RATE, 3)

    return wav_bytes, duration_s, elapsed_ms


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Kokoro TTS",
    version="1.0.0",
    description="Kokoro-82M multi-language neural text-to-speech service",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


# ── Health / Info ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health() -> dict:
    """Liveness probe — reports ready once the default pipeline is loaded."""
    ready = _DEFAULT_LANG in _pipelines
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Default pipeline not yet loaded",
        )
    return {"status": "ok", "default_voice": _DEFAULT_VOICE, "default_lang": _DEFAULT_LANG}


@app.get("/info", tags=["System"])
async def info() -> dict:
    return {
        "default_voice": _DEFAULT_VOICE,
        "default_speed": _DEFAULT_SPEED,
        "default_lang": _DEFAULT_LANG,
        "sample_rate": _SAMPLE_RATE,
        "loaded_languages": list(_pipelines.keys()),
        "load_s": round(_startup_ts, 2),
    }


@app.get("/voices", tags=["Voices"])
async def voices() -> dict:
    """Return the full voice list grouped by language."""
    return {
        "sample_rate": _SAMPLE_RATE,
        "voices": {
            "a": {
                "label": "American English",
                "voices": ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
                           "am_adam", "am_michael", "am_fenrir", "am_liam", "am_puck"],
            },
            "b": {
                "label": "British English",
                "voices": ["bf_emma", "bf_isabella", "bm_george", "bm_lewis"],
            },
            "hi": {
                "label": "Hindi",
                "voices": ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"],
            },
            "es": {
                "label": "Spanish",
                "voices": ["ef_daria", "em_alex", "em_santa"],
            },
            "fr": {
                "label": "French",
                "voices": ["ff_siwis"],
            },
            "it": {
                "label": "Italian",
                "voices": ["if_sara", "im_nicola"],
            },
            "ja": {
                "label": "Japanese",
                "voices": ["jf_alpha", "jf_gongitsune", "jm_kumo"],
            },
            "ko": {
                "label": "Korean",
                "voices": ["kf_alpha", "km_hyun"],
            },
            "pt": {
                "label": "Portuguese",
                "voices": ["pf_dora", "pm_alex"],
            },
            "zh": {
                "label": "Chinese",
                "voices": ["zf_xiaobei", "zf_xiaoni", "zm_yunjian"],
            },
        },
    }


# ── TTS Endpoints ─────────────────────────────────────────────────────────────

@app.post(
    "/tts",
    tags=["TTS"],
    summary="Synthesise text to WAV audio",
    responses={
        200: {
            "content": {"audio/wav": {}},
            "description": "16-bit PCM WAV audio at 24 000 Hz mono",
        }
    },
)
async def tts(req: TTSRequest) -> Response:
    """
    Convert *text* to speech and return a WAV audio file.

    The full audio is generated in one shot then returned.
    For low-latency streaming pipelines, use ``POST /tts/stream`` instead.
    """
    try:
        wav_bytes, duration_s, elapsed_ms = _synthesise(req)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("tts.synthesis_error", voice=req.voice, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Synthesis failed: {exc}",
        ) from exc

    logger.info(
        "tts.ok",
        voice=req.voice,
        lang=req.lang,
        chars=len(req.text),
        duration_s=duration_s,
        elapsed_ms=elapsed_ms,
        # time-to-first-byte equals elapsed_ms for blocking endpoint
        ttfb_ms=elapsed_ms,
    )

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-Audio-Duration-S": str(duration_s),
            "X-Elapsed-MS": str(elapsed_ms),
            "X-Voice": req.voice,
        },
    )


@app.post(
    "/tts/stream",
    tags=["TTS"],
    summary="Stream TTS audio chunk-by-chunk (low latency)",
    responses={
        200: {
            "content": {"audio/wav": {}},
            "description": "Chunked WAV stream — each chunk is one WAV segment",
        }
    },
)
async def tts_stream(req: TTSRequest) -> StreamingResponse:
    """
    Stream audio as it is synthesised sentence-by-sentence.

    Each yielded chunk is a self-contained WAV bytes segment so the client
    can begin playing immediately at < 150ms TTFB for short utterances.

    This endpoint is designed for real-time voice pipelines (pipecat, WebRTC).
    """
    try:
        pipeline = _get_pipeline(req.lang)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    def _generate():
        t_start = time.perf_counter()
        first_chunk_sent = False
        generator = pipeline(req.text, voice=req.voice, speed=req.speed)

        for _graphemes, _phonemes, audio_chunk in generator:
            if audio_chunk is None or len(audio_chunk) == 0:
                continue

            audio = np.clip(audio_chunk.astype(np.float32), -1.0, 1.0)
            chunk_wav = _numpy_to_wav(audio)

            if not first_chunk_sent:
                ttfb_ms = round((time.perf_counter() - t_start) * 1000, 1)
                logger.info(
                    "tts.stream_first_chunk",
                    voice=req.voice,
                    lang=req.lang,
                    ttfb_ms=ttfb_ms,
                )
                first_chunk_sent = True

            yield chunk_wav

    return StreamingResponse(
        _generate(),
        media_type="audio/wav",
        headers={"X-Voice": req.voice, "X-Lang": req.lang},
    )

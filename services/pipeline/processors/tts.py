"""
KokoroTTSProcessor — TextFrame → TTSAudioRawFrame (streaming).

Connects to the Kokoro TTS WebSocket (`/tts/stream`), sends text chunks as
JSON, and emits TTSAudioRawFrames for each WAV chunk received.  The first audio
packet is pushed downstream before the full sentence is finished — targeting
< 150 ms stream-to-stream latency on short utterances.

Design notes
------------
* One persistent WebSocket per session; reconnects on failure (fail-open).
* LLM text chunks are accumulated by sentence boundary, then dispatched to
  Kokoro in order — small fragments keep TTFB low without thrashing the WS.
* Audio level is normalised to −20 LUFS (RMS-approximation) before emission.
* ``pre_warm()`` can be called after ``StartFrame`` to prime the Kokoro
  phoneme cache with common phrases, reducing first-utterance latency.
* When a ``StartInterruptionFrame`` arrives the pending buffer is flushed.
* Optional ``CallRecorder`` receives every outbound PCM chunk via
  ``write_outbound()`` for post-call stereo mixing.

Env vars
--------
  KOKORO_URL        ws://kokoro-1:8880/tts/stream
  TTS_VOICE         af_heart
  TTS_SPEED         1.0
  TTS_LANG          a
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import time
from typing import Any

import numpy as np
import soundfile as sf
import structlog
import websockets
import websockets.asyncio.client as ws_client
from pipecat.frames.frames import (
    AudioRawFrame,
    EndFrame,
    Frame,
    StartFrame,
    StartInterruptionFrame,
    TextFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

_KOKORO_URL_DEFAULT = os.getenv("KOKORO_URL", "ws://kokoro-1:8880/tts/stream")
_SENTENCE_SPLIT_RE  = re.compile(r'(?<=[.!?])\s+')

# Minimum chars to accumulate before dispatching — balances TTFB vs churn
_MIN_DISPATCH_CHARS = 10

# Target integrated loudness for outbound audio
_TARGET_LUFS: float = -20.0

# Maximum linear gain applied during LUFS normalisation (prevents over-amplification)
_MAX_GAIN: float = 10.0

# Seconds to wait before retrying a failed WS connection
_RECONNECT_DELAY: float = 3.0

# ── Voice catalogue ──────────────────────────────────────────────────────────

#: Mapping of Kokoro voice identifier → human-readable label.
VOICE_MAP: dict[str, str] = {
    "af_heart":    "American Female (warm)",
    "af_sky":      "American Female (clear)",
    "am_adam":     "American Male",
    "am_michael":  "American Male (deep)",
    "bf_emma":     "British Female",
    "bf_isabella": "British Female (soft)",
    "bm_george":   "British Male",
    "bm_lewis":    "British Male (crisp)",
}


class KokoroTTSProcessor(FrameProcessor):
    """
    Streams TTS synthesis via the Kokoro WebSocket service.

    Parameters
    ----------
    kokoro_url : str
        WebSocket URL of the Kokoro service (``/tts/stream`` path).
    voice : str
        Kokoro voice identifier (e.g. ``'af_heart'``).  See ``VOICE_MAP``.
    speed : float
        Speech-rate multiplier (0.25 – 3.0); 1.0 = normal.
    lang : str
        Kokoro lang code (``'a'`` = American EN).
    recorder : Any | None
        Optional ``CallRecorder`` instance.  When provided,
        ``recorder.write_outbound(pcm)`` is called for every audio chunk
        pushed downstream so the call can be mixed and stored after the
        session ends.
    """

    def __init__(
        self,
        kokoro_url: str      = _KOKORO_URL_DEFAULT,
        voice: str           = os.getenv("TTS_VOICE", "af_heart"),
        speed: float         = float(os.getenv("TTS_SPEED", "1.0")),
        lang: str            = os.getenv("TTS_LANG", "a"),
        recorder: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._kokoro_url       = kokoro_url
        self._voice            = voice
        self._speed            = speed
        self._lang             = lang
        self._recorder         = recorder
        self._ws: ws_client.ClientConnection | None = None
        self._text_buffer: str = ""
        self._interrupted: bool = False
        self._unavailable: bool = False
        self._reconnect_task: asyncio.Task | None = None
        self._log = logger.bind(processor="KokoroTTS", voice=voice)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self._connect()
            await self.push_frame(frame, direction)

        elif isinstance(frame, TextFrame):
            if not self._unavailable:
                self._text_buffer += frame.text
                await self._maybe_dispatch()

        elif isinstance(frame, StartInterruptionFrame):
            self._interrupted = True
            self._text_buffer = ""
            self._log.info("kokoro_tts.interrupted")
            await self.push_frame(frame, direction)

        elif isinstance(frame, EndFrame):
            if self._text_buffer.strip() and not self._unavailable:
                await self._dispatch(self._text_buffer.strip())
                self._text_buffer = ""
            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()
            await self._close()
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Connection management ────────────────────────────────────────────────

    async def _connect(self) -> None:
        self._log.info("kokoro_tts.connecting")
        try:
            self._ws = await ws_client.connect(self._kokoro_url, open_timeout=10)
            self._unavailable = False
            self._log.info("kokoro_tts.connected")
        except Exception as exc:
            self._log.warning(
                "kokoro_tts.connect_failed",
                error=str(exc),
                url=self._kokoro_url,
            )
            self._ws = None
            self._unavailable = True
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Spawn a background task to retry the connection after a short delay."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop(), name="kokoro_tts_reconnect"
        )

    async def _reconnect_loop(self) -> None:
        await asyncio.sleep(_RECONNECT_DELAY)
        self._log.info("kokoro_tts.reconnect_attempt")
        await self._connect()

    async def _close(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    # ── Text accumulation / dispatch ─────────────────────────────────────────

    async def _maybe_dispatch(self) -> None:
        """Dispatch complete sentences as they accumulate."""
        parts = _SENTENCE_SPLIT_RE.split(self._text_buffer)
        if len(parts) > 1:
            to_send = " ".join(parts[:-1]).strip()
            self._text_buffer = parts[-1]
            if to_send and len(to_send) >= _MIN_DISPATCH_CHARS:
                await self._dispatch(to_send)

    async def _dispatch(self, text: str) -> None:
        """Send *text* to Kokoro and push each received WAV chunk downstream."""
        if not text or self._interrupted:
            self._interrupted = False
            return

        if self._unavailable:
            self._log.warning("kokoro_tts.unavailable — skipping dispatch")
            return

        if not self._ws:
            self._log.warning("kokoro_tts.not_connected — reconnecting")
            await self._connect()
            if not self._ws:
                return  # still unavailable after reconnect attempt

        payload = json.dumps({
            "text":  text,
            "voice": self._voice,
            "speed": self._speed,
            "lang":  self._lang,
        })

        dispatch_start = time.perf_counter()
        first_audio = True

        try:
            await self._ws.send(payload)

            while True:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=15.0)

                if isinstance(msg, bytes):
                    pcm = _wav_bytes_to_pcm(msg)
                    if pcm is not None:
                        pcm = _normalize_lufs(pcm, _TARGET_LUFS)

                        if first_audio:
                            ttfb_ms = (time.perf_counter() - dispatch_start) * 1000
                            self._log.info(
                                "kokoro_tts.first_audio",
                                ttfb_ms=round(ttfb_ms, 1),
                                chars=len(text),
                            )
                            first_audio = False

                        if self._recorder is not None:
                            self._recorder.write_outbound(pcm)

                        await self.push_frame(
                            TTSAudioRawFrame(audio=pcm, sample_rate=24000, num_channels=1)
                        )

                elif isinstance(msg, str):
                    jmsg = json.loads(msg)
                    if jmsg.get("done"):
                        total_ms = (time.perf_counter() - dispatch_start) * 1000
                        self._log.debug(
                            "kokoro_tts.chunk_done",
                            chars=len(text),
                            total_ms=round(total_ms, 1),
                            server_elapsed_ms=jmsg.get("elapsed_ms"),
                        )
                        break
                    if "error" in jmsg:
                        self._log.error("kokoro_tts.server_error", error=jmsg["error"])
                        break

        except (websockets.ConnectionClosed, asyncio.TimeoutError) as exc:
            self._log.warning("kokoro_tts.connection_lost", error=str(exc))
            self._ws = None
            self._unavailable = True
            self._schedule_reconnect()
        except Exception as exc:
            self._log.exception("kokoro_tts.unexpected_error", error=str(exc))

    # ── Phoneme pre-warm ─────────────────────────────────────────────────────

    async def pre_warm(self, phrases: list[str]) -> None:
        """
        Send *phrases* to Kokoro to prime the server-side phoneme cache.

        Audio responses are silently discarded — this only warms Kokoro's
        internal synthesis pipeline to reduce TTFB on the first real utterance.

        Should be called after ``StartFrame`` has been processed (i.e. after
        ``_connect()`` has succeeded).
        """
        if self._unavailable or not self._ws:
            self._log.debug("kokoro_tts.pre_warm_skipped", reason="not_connected")
            return

        self._log.info("kokoro_tts.pre_warm_start", phrase_count=len(phrases))
        for phrase in phrases:
            if phrase.strip():
                await _drain_ws(self._ws, phrase, self._voice, self._speed, self._lang)
        self._log.info("kokoro_tts.pre_warm_done")

    # ── Voice / speed control (mid-session) ──────────────────────────────────

    def set_voice(self, voice: str, lang: str | None = None) -> None:
        """Switch the active voice (and optionally lang code) mid-session."""
        self._voice = voice
        if lang:
            self._lang = lang

    def set_speed(self, speed: float) -> None:
        """Clamp and set speech-rate multiplier."""
        self._speed = max(0.25, min(3.0, speed))


# ── Module-level helpers ──────────────────────────────────────────────────────

async def _drain_ws(
    ws: ws_client.ClientConnection,
    text: str,
    voice: str,
    speed: float,
    lang: str,
) -> None:
    """Send one phrase to *ws* and drain the response without emitting frames."""
    payload = json.dumps({"text": text, "voice": voice, "speed": speed, "lang": lang})
    try:
        await ws.send(payload)
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
            if isinstance(msg, str):
                jmsg = json.loads(msg)
                if jmsg.get("done") or "error" in jmsg:
                    break
    except Exception as exc:
        logger.warning("kokoro_tts.pre_warm_error", error=str(exc))


def _normalize_lufs(pcm_bytes: bytes, target_lufs: float = _TARGET_LUFS) -> bytes:
    """
    Normalise raw int16 PCM to approximately *target_lufs* integrated loudness.

    Uses a simplified RMS-based approximation:

    .. math::

        \\text{LUFS} \\approx -0.691 + 10 \\cdot \\log_{10}(\\overline{x^2})

    Gain is capped at ``_MAX_GAIN`` (10×) to prevent over-amplification of
    near-silence frames.  Silent frames (mean-square < 10⁻⁹) are returned
    unchanged.
    """
    if not pcm_bytes:
        return pcm_bytes

    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    ms = float(np.mean(samples ** 2))
    if ms < 1e-9:
        return pcm_bytes

    current_lufs = -0.691 + 10.0 * np.log10(ms)
    gain_db = target_lufs - current_lufs
    gain = min(10.0 ** (gain_db / 20.0), _MAX_GAIN)
    normalised = np.clip(samples * gain, -1.0, 1.0)
    return (normalised * 32767.0).astype(np.int16).tobytes()


def _wav_bytes_to_pcm(wav_bytes: bytes) -> bytes | None:
    """
    Decode a WAV byte buffer to raw int16 PCM bytes.

    Returns ``None`` (and logs a warning) if decoding fails.
    """
    try:
        buf = io.BytesIO(wav_bytes)
        audio, _sr = sf.read(buf, dtype="int16", always_2d=False)
        return audio.tobytes()
    except Exception as exc:
        logger.warning("kokoro_tts.wav_decode_error", error=str(exc))
        return None

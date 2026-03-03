"""
KokoroTTSProcessor — TextFrame → AudioRawFrame (streaming).

Connects to the Kokoro TTS WebSocket (`/tts/stream`), sends text chunks as
JSON, and emits AudioRawFrames for each WAV chunk received.  The first audio
packet is pushed downstream before the full sentence is finished — enabling
< 200ms TTFB on short utterances.

Design notes
------------
* One persistent WebSocket per session (reconnects on failure).
* LLM text chunks are accumulated by sentence boundary, then dispatched to
  Kokoro in order — small fragments keep TTFB low without thrashing the
  Kokoro connection.
* When an StartInterruptionFrame arrives, the pending TTS is cancelled and the
  audio buffer is flushed.

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

# Minimum chars to accumulate before dispatching — balances TTFB vs connection churn
_MIN_DISPATCH_CHARS = 10


class KokoroTTSProcessor(FrameProcessor):
    """
    Streams TTS synthesis via the Kokoro WebSocket service.

    Parameters
    ----------
    kokoro_url : str
        WebSocket URL of the Kokoro service (`/tts/stream` path).
    voice : str
        Kokoro voice identifier (e.g. ``'af_heart'``).
    speed : float
        Speech-rate multiplier (0.25–3.0); 1.0 = normal.
    lang : str
        Kokoro lang_code (``'a'`` = American EN).
    """

    def __init__(
        self,
        kokoro_url: str     = _KOKORO_URL_DEFAULT,
        voice: str          = os.getenv("TTS_VOICE", "af_heart"),
        speed: float        = float(os.getenv("TTS_SPEED", "1.0")),
        lang: str           = os.getenv("TTS_LANG", "a"),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._kokoro_url  = kokoro_url
        self._voice       = voice
        self._speed       = speed
        self._lang        = lang
        self._ws: ws_client.ClientConnection | None = None
        self._text_buffer: str = ""
        self._interrupted: bool = False
        self._log = logger.bind(processor="KokoroTTS", voice=voice)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self._connect()
            await self.push_frame(frame, direction)

        elif isinstance(frame, TextFrame):
            # Accumulate LLM text and dispatch by sentence
            self._text_buffer += frame.text
            await self._maybe_dispatch()

        elif isinstance(frame, StartInterruptionFrame):
            # User started speaking — cancel pending synthesis
            self._interrupted = True
            self._text_buffer = ""
            self._log.info("kokoro_tts.interrupted")
            await self.push_frame(frame, direction)

        elif isinstance(frame, EndFrame):
            # Flush any remaining text before shutting down
            if self._text_buffer.strip():
                await self._dispatch(self._text_buffer.strip())
                self._text_buffer = ""
            await self._close()
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Internal ────────────────────────────────────────────────────────────

    async def _connect(self) -> None:
        self._log.info("kokoro_tts.connecting")
        self._ws = await ws_client.connect(self._kokoro_url, open_timeout=10)
        self._log.info("kokoro_tts.connected")

    async def _close(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _maybe_dispatch(self) -> None:
        """Dispatch complete sentences as they accumulate."""
        parts = _SENTENCE_SPLIT_RE.split(self._text_buffer)
        if len(parts) > 1:
            # Send all complete sentences; keep the incomplete trailing part
            to_send = " ".join(parts[:-1]).strip()
            self._text_buffer = parts[-1]
            if to_send and len(to_send) >= _MIN_DISPATCH_CHARS:
                await self._dispatch(to_send)

    async def _dispatch(self, text: str) -> None:
        """Send text to Kokoro WS and push each received WAV chunk downstream."""
        if not text or self._interrupted:
            self._interrupted = False
            return

        if not self._ws:
            self._log.warning("kokoro_tts.not_connected — reconnecting")
            await self._connect()

        payload = json.dumps({
            "text":  text,
            "voice": self._voice,
            "speed": self._speed,
            "lang":  self._lang,
        })

        try:
            await self._ws.send(payload)

            while True:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=15.0)

                if isinstance(msg, bytes):
                    # Decode WAV chunk and re-emit as AudioRawFrame
                    pcm = _wav_bytes_to_pcm(msg)
                    if pcm is not None:
                        await self.push_frame(
                            TTSAudioRawFrame(audio=pcm, sample_rate=24000, num_channels=1)
                        )
                elif isinstance(msg, str):
                    jmsg = json.loads(msg)
                    if jmsg.get("done"):
                        self._log.debug(
                            "kokoro_tts.chunk_done",
                            chars=len(text),
                            elapsed_ms=jmsg.get("elapsed_ms"),
                        )
                        break
                    if "error" in jmsg:
                        self._log.error("kokoro_tts.server_error", error=jmsg["error"])
                        break

        except (websockets.ConnectionClosed, asyncio.TimeoutError) as exc:
            self._log.warning("kokoro_tts.connection_lost", error=str(exc))
            self._ws = None
        except Exception as exc:
            self._log.exception("kokoro_tts.unexpected_error", error=str(exc))

    # ── Voice / speed control (can be called mid-session) ────────────────────

    def set_voice(self, voice: str, lang: str | None = None) -> None:
        self._voice = voice
        if lang:
            self._lang = lang

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.25, min(3.0, speed))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wav_bytes_to_pcm(wav_bytes: bytes) -> bytes | None:
    """
    Decode a WAV byte buffer to raw int16 PCM bytes.

    Returns None and logs a warning if decoding fails.
    """
    try:
        buf = io.BytesIO(wav_bytes)
        audio_f32, _sr = sf.read(buf, dtype="int16", always_2d=False)
        return audio_f32.tobytes()
    except Exception as exc:
        logger.warning("kokoro_tts.wav_decode_error", error=str(exc))
        return None

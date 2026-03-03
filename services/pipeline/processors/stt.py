"""
WhisperSTTProcessor — AudioRawFrame → TranscriptionFrame.

Connects to the Whisper service WebSocket (`/transcribe/stream`), streams
raw int16 PCM audio, and emits a TranscriptionFrame when the accumulation END
response arrives.

Key design decisions
--------------------
* One persistent WebSocket connection per processor instance — reconnects on
  disconnect with exponential back-off.
* Audio is accumulated in a bytearray until VAD signals end-of-utterance by
  pushing an EndFrame or UserStoppedSpeakingFrame.  On that event, b"END" is
  sent to the Whisper service, which responds with the transcript JSON.
* The Whisper WS result is awaited before the next utterance starts, matching
  the turn-based conversation model.

Env vars (read at import time, can be overridden per-instance)
-----------
  WHISPER_URL   ws://whisper-1:9000/transcribe/stream
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
import websockets
import websockets.asyncio.client as ws_client
from pipecat.frames.frames import (
    AudioRawFrame,
    EndFrame,
    Frame,
    StartFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

_WHISPER_URL_DEFAULT = os.getenv(
    "WHISPER_URL", "ws://whisper-1:9000/transcribe/stream"
)
_RECONNECT_DELAY_S = 2.0
_MAX_RECONNECT_DELAY_S = 30.0


class WhisperSTTProcessor(FrameProcessor):
    """
    Streams accumulated audio to the Whisper WebSocket service and emits
    TranscriptionFrames downstream.

    Parameters
    ----------
    whisper_url : str
        WebSocket URL of the Whisper service (`/transcribe/stream` path).
    language : str | None
        BCP-47 language hint; ``None`` triggers auto-detection.
    """

    def __init__(
        self,
        whisper_url: str = _WHISPER_URL_DEFAULT,
        language: str | None = None,
        on_transcription: Callable[[str, str | None], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._whisper_url     = whisper_url
        self._language        = language
        self._on_transcription = on_transcription
        self._ws: ws_client.ClientConnection | None = None
        self._audio_buffer: bytearray = bytearray()
        self._reconnect_delay: float = _RECONNECT_DELAY_S
        self._unavailable: bool = False
        self._log = logger.bind(processor="WhisperSTT", url=whisper_url)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self._connect()
            await self.push_frame(frame, direction)

        elif isinstance(frame, AudioRawFrame):
            # Accumulate raw PCM bytes (int16, 16 kHz mono)
            self._audio_buffer.extend(frame.audio)

        elif isinstance(frame, UserStoppedSpeakingFrame):
            # VAD reported end-of-utterance — flush to Whisper
            await self._flush_and_transcribe()
            await self.push_frame(frame, direction)

        elif isinstance(frame, EndFrame):
            await self._close()
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Internal ────────────────────────────────────────────────────────────

    async def _connect(self) -> None:
        """Open (or re-open) WebSocket connection to the Whisper service.

        Appends a ``?language=<code>`` query param when a language hint is
        configured so the Whisper server can skip language detection and reduce
        latency by ~30–80 ms per utterance.
        """
        url = self._whisper_url
        if self._language:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}language={self._language}"

        try:
            self._log.info("whisper_stt.connecting", url=url)
            self._ws = await ws_client.connect(url, open_timeout=10)
            self._unavailable = False
            self._reconnect_delay = _RECONNECT_DELAY_S
            self._log.info("whisper_stt.connected")
        except Exception as exc:
            self._log.error(
                "whisper_stt.connection_failed",
                error=str(exc),
                url=url,
            )
            self._unavailable = True
            self._ws = None

    async def _close(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _flush_and_transcribe(self) -> None:
        """Send accumulated audio + END marker, wait for transcript, emit frame.

        Measures client-side round-trip latency (``latency_ms``) and logs it
        alongside the server-reported processing time (``server_elapsed_ms``).
        When the Whisper service is unavailable the audio buffer is cleared and
        a background reconnect is scheduled so the pipeline keeps running.
        """
        if not self._audio_buffer:
            return

        # Whisper service is down — drop utterance and try to reconnect
        if self._unavailable or not self._ws:
            self._log.warning(
                "whisper_stt.unavailable",
                action="dropping_utterance",
                buffered_bytes=len(self._audio_buffer),
            )
            self._audio_buffer.clear()
            asyncio.create_task(self._connect())  # non-blocking reconnect attempt
            return

        try:
            audio_bytes = bytes(self._audio_buffer)
            self._audio_buffer.clear()

            t0 = time.perf_counter()

            # Stream audio in 4 KB chunks then signal end-of-utterance
            chunk_size = 4096
            for offset in range(0, len(audio_bytes), chunk_size):
                await self._ws.send(audio_bytes[offset : offset + chunk_size])
            await self._ws.send(b"END")

            # Wait for transcript (Whisper responds after END)
            raw = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
            latency_ms = round((time.perf_counter() - t0) * 1000)

            result: dict = json.loads(raw)

            if "error" in result:
                self._log.error(
                    "whisper_stt.server_error",
                    error=result["error"],
                    latency_ms=latency_ms,
                )
                return

            text     = result.get("text", "").strip()
            language = result.get("language")

            if text:
                self._log.info(
                    "whisper_stt.transcription",
                    text=text[:80],
                    language=language,
                    latency_ms=latency_ms,
                    server_elapsed_ms=result.get("elapsed_ms"),
                )
                await self.push_frame(
                    TranscriptionFrame(
                        text=text,
                        user_id="caller",
                        timestamp=latency_ms,
                    )
                )
                if self._on_transcription is not None:
                    await self._on_transcription(text, language)
            else:
                self._log.debug(
                    "whisper_stt.empty_transcript",
                    latency_ms=latency_ms,
                )

        except (websockets.ConnectionClosed, asyncio.TimeoutError) as exc:
            self._log.warning("whisper_stt.connection_lost", error=str(exc))
            self._ws = None
            self._unavailable = True
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(
                self._reconnect_delay * 2, _MAX_RECONNECT_DELAY_S
            )
            await self._connect()

        except Exception as exc:
            self._log.exception("whisper_stt.unexpected_error", error=str(exc))

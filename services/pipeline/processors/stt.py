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
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._whisper_url = whisper_url
        self._language    = language
        self._ws: ws_client.ClientConnection | None = None
        self._audio_buffer: bytearray = bytearray()
        self._reconnect_delay: float = _RECONNECT_DELAY_S
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
        """Open (or re-open) WebSocket connection to the Whisper service."""
        self._log.info("whisper_stt.connecting")
        self._ws = await ws_client.connect(self._whisper_url, open_timeout=10)
        self._reconnect_delay = _RECONNECT_DELAY_S
        self._log.info("whisper_stt.connected")

    async def _close(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _flush_and_transcribe(self) -> None:
        """Send accumulated audio + END marker, wait for transcript, emit frame."""
        if not self._audio_buffer:
            return

        if not self._ws:
            self._log.warning("whisper_stt.not_connected — dropping utterance")
            self._audio_buffer.clear()
            return

        try:
            audio_bytes = bytes(self._audio_buffer)
            self._audio_buffer.clear()

            # Stream audio in 4 KB chunks then signal end-of-utterance
            chunk_size = 4096
            for offset in range(0, len(audio_bytes), chunk_size):
                await self._ws.send(audio_bytes[offset : offset + chunk_size])
            await self._ws.send(b"END")

            # Wait for transcript (Whisper responds after END)
            raw = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
            result: dict = json.loads(raw)

            if "error" in result:
                self._log.error("whisper_stt.server_error", error=result["error"])
                return

            text = result.get("text", "").strip()
            if text:
                self._log.info(
                    "whisper_stt.transcription",
                    text=text[:80],
                    language=result.get("language"),
                    elapsed_ms=result.get("elapsed_ms"),
                )
                await self.push_frame(
                    TranscriptionFrame(
                        text=text,
                        user_id="caller",
                        timestamp=result.get("elapsed_ms"),
                    )
                )
            else:
                self._log.debug("whisper_stt.empty_transcript")

        except (websockets.ConnectionClosed, asyncio.TimeoutError) as exc:
            self._log.warning("whisper_stt.connection_lost", error=str(exc))
            self._ws = None
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(
                self._reconnect_delay * 2, _MAX_RECONNECT_DELAY_S
            )
            await self._connect()

        except Exception as exc:
            self._log.exception("whisper_stt.unexpected_error", error=str(exc))

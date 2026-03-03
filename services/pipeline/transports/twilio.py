"""
Twilio transport stub for the Pipeline Service.

Bridges a Pipecat pipeline to a Twilio PSTN call via a ``<Stream>`` TwiML
verb (Media Streams).  Twilio sends audio over a WebSocket as µ-law (PCMU)
8 kHz; this transport re-samples both directions to the pipeline's 16 kHz
int16 PCM format.

Wire protocol (Twilio Media Streams)
-------------------------------------
* Inbound (Twilio → Server):  JSON messages with ``event: media``,
  ``media.payload`` as base64 PCMU 8 kHz.
* Outbound (Server → Twilio): JSON ``{event:"media", streamSid:...,
  media:{payload:<base64 PCMU 8kHz>}}``.

Integration steps
-----------------
1. Configure a Twilio phone number with a Voice Webhook pointing to
   ``/twilio/voice`` on this service's public URL.
2. Reply with TwiML ``<Connect><Stream url="wss://..."/></Connect>``.
3. A persistent WebSocket will be opened by Twilio to
   ``/sessions/{id}/twilio_stream``.

See Also
--------
* https://www.twilio.com/docs/voice/twiml/stream
* pipecat.transports.services.helpers.daily_rest (for reference patterns)
"""
from __future__ import annotations

import audioop        # stdlib mulaw codec  (Python ≤ 3.12; use audioop-lts on 3.13+)
import base64
import json
import logging
from typing import AsyncGenerator

import structlog
from fastapi import WebSocket
from pipecat.frames.frames import AudioRawFrame, EndFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

log: structlog.BoundLogger = structlog.get_logger(__name__)

_TWILIO_RATE = 8_000      # Twilio always sends 8 kHz PCMU
_PIPELINE_RATE = 16_000   # pipeline operates at 16 kHz


def _mulaw_to_pcm16(payload_b64: str) -> bytes:
    """Decode base64 µ-law 8 kHz → int16 PCM 8 kHz."""
    mulaw_bytes = base64.b64decode(payload_b64)
    pcm8 = audioop.ulaw2lin(mulaw_bytes, 2)   # int16 at 8 kHz
    return pcm8


def _pcm8_to_16(pcm8: bytes) -> bytes:
    """Up-sample int16 PCM from 8 kHz to 16 kHz (linear interpolation)."""
    pcm16, _ = audioop.ratecv(
        pcm8, 2, 1, _TWILIO_RATE, _PIPELINE_RATE, None
    )
    return pcm16


def _pcm16_to_8_mulaw(pcm16: bytes) -> bytes:
    """Down-sample int16 PCM 16 kHz → 8 kHz, then encode as µ-law."""
    pcm8, _ = audioop.ratecv(
        pcm16, 2, 1, _PIPELINE_RATE, _TWILIO_RATE, None
    )
    return audioop.lin2ulaw(pcm8, 2)


class TwilioTransport(FrameProcessor):
    """
    Pipecat ``FrameProcessor`` wrapping a Twilio Media Stream WebSocket.

    * **Downstream**: reads Twilio ``media`` events, converts µ-law→PCM,
      up-samples to 16 kHz, and pushes ``AudioRawFrame``.
    * **Upstream**: accepts ``AudioRawFrame`` (16 kHz int16), down-samples
      to 8 kHz, encodes as µ-law, and sends back to Twilio.
    """

    def __init__(self, websocket: WebSocket, stream_sid: str) -> None:
        super().__init__()
        self._ws = websocket
        self._stream_sid = stream_sid
        self._active = True

    # ------------------------------------------------------------------
    # FrameProcessor
    # ------------------------------------------------------------------

    async def process_frame(
        self, frame: object, direction: FrameDirection
    ) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, EndFrame):
            self._active = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, AudioRawFrame):
            # Outbound: pipeline → Twilio
            mulaw = _pcm16_to_8_mulaw(frame.audio)
            payload = base64.b64encode(mulaw).decode()
            msg = json.dumps(
                {
                    "event": "media",
                    "streamSid": self._stream_sid,
                    "media": {"payload": payload},
                }
            )
            try:
                await self._ws.send_text(msg)
            except Exception as exc:
                log.warning("twilio_send_error", error=str(exc))
            return

        await self.push_frame(frame, direction)

    # ------------------------------------------------------------------
    # Inbound reader
    # ------------------------------------------------------------------

    async def read_frames(self) -> AsyncGenerator[AudioRawFrame, None]:
        """
        Yield ``AudioRawFrame`` objects decoded from Twilio's Media Stream.

        Call this inside the pipeline's input loop.
        """
        while self._active:
            try:
                raw = await self._ws.receive_text()
            except Exception as exc:
                log.info("twilio_ws_closed", reason=str(exc))
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event = msg.get("event")
            if event == "media":
                payload = msg["media"]["payload"]
                pcm8 = _mulaw_to_pcm16(payload)
                pcm16 = _pcm8_to_16(pcm8)
                yield AudioRawFrame(
                    audio=pcm16,
                    sample_rate=_PIPELINE_RATE,
                    num_channels=1,
                )
            elif event == "stop":
                log.info("twilio_stream_stopped", stream_sid=self._stream_sid)
                self._active = False
                break

"""
WebSocket transport for the Pipeline Service.

Wraps ``pipecat.transports.websocket.fastapi.FastAPIWebsocketTransport``
to provide a clean ``input()`` / ``output()`` source/sink pair for the pipeline
builder.  Framings emitted downstream:

* ``AudioRawFrame``           — raw int16 PCM at 16 kHz, 1 ch, 320-sample chunks
* ``TextFrame``               — JSON text frames sent as UTF-8 text messages
* ``TTSAudioRawFrame``        — output audio sent upstream as binary to client

Wire protocol (binary direction):
  Client → Server : raw int16 PCM chunks (little-endian, 16 kHz mono)
  Server → Client : raw int16 PCM chunks for audio,
                    UTF-8 JSON text messages for events

Usage::

    transport = WebSocketTransport(websocket, params)
    pipeline  = await PipelineBuilder(cfg).build(transport)
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

import structlog
from fastapi import WebSocket
from pipecat.frames.frames import (
    AudioRawFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    TextFrame,
    TTSAudioRawFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

if TYPE_CHECKING:
    from pipecat.pipeline.task import PipelineTask

log: structlog.BoundLogger = structlog.get_logger(__name__)


class RawPCMSerializer(FrameSerializer):
    """
    Minimal serializer for raw int16 PCM WebSocket transport.

    Wire format
    -----------
    Client → Server : raw int16 PCM bytes (little-endian, 16 kHz mono)
    Server → Client : raw int16 PCM bytes for audio responses

    No framing headers, no WAV, no RTVI — pure PCM bytes on the wire.
    """

    def __init__(self, sample_rate: int = 16_000, num_channels: int = 1) -> None:
        super().__init__()
        self._sample_rate = sample_rate
        self._num_channels = num_channels

    async def serialize(self, frame: Frame) -> bytes | None:
        """Convert an output audio frame to raw PCM bytes; ignore all other frames."""
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        """Convert raw PCM bytes from the client into an InputAudioRawFrame."""
        if not isinstance(data, (bytes, bytearray)):
            return None
        return InputAudioRawFrame(
            audio=bytes(data),
            sample_rate=self._sample_rate,
            num_channels=self._num_channels,
        )


def make_ws_transport(
    websocket: WebSocket,
    *,
    sample_rate: int = 16_000,
    channels: int = 1,
    audio_chunk_ms: int = 20,
) -> FastAPIWebsocketTransport:
    """
    Build a ``FastAPIWebsocketTransport`` configured for raw int16 PCM I/O.

    Parameters
    ----------
    websocket:
        The raw Starlette / FastAPI WebSocket connection.
    sample_rate:
        PCM sample-rate expected on inbound and outbound; default 16 kHz.
    channels:
        Number of audio channels; default 1 (mono).
    audio_chunk_ms:
        Target chunk duration for outgoing audio in milliseconds; default 20 ms.

    Notes
    -----
    A ``RawPCMSerializer`` is provided so that binary WebSocket messages are
    deserialized into ``InputAudioRawFrame`` objects and outbound
    ``OutputAudioRawFrame`` objects are serialized back to raw bytes.
    Without a serializer pipecat 0.0.104 silently drops every incoming message.

    Returns
    -------
    FastAPIWebsocketTransport
        A fully configured transport ready to be passed to ``PipelineBuilder``.
    """
    serializer = RawPCMSerializer(sample_rate=sample_rate, num_channels=channels)

    params = FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,              # raw PCM — no WAV header on the wire
        audio_in_sample_rate=sample_rate,
        audio_out_sample_rate=sample_rate,
        audio_out_channels=channels,
        audio_out_10ms_chunks=audio_chunk_ms // 10,
        vad_enabled=False,                 # VAD handled by SileroVADProcessor
        serializer=serializer,
    )

    transport = FastAPIWebsocketTransport(websocket=websocket, params=params)
    log.debug(
        "websocket_transport_created",
        sample_rate=sample_rate,
        channels=channels,
        chunk_ms=audio_chunk_ms,
    )
    return transport

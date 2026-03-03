"""
WebRTC transport stub for the Pipeline Service.

Provides an ``aiortc``-based audio transport so that browser clients can
connect using standard WebRTC (ICE / DTLS / SRTP) instead of raw WebSocket
PCM.  This module exposes:

* ``WebRTCTransport``        — thin wrapper; adapts ``aiortc`` MediaStreamTrack
                               to Pipecat ``AudioRawFrame`` stream
* ``create_offer_answer()``  — SDP exchange helper for the signalling endpoint

Wire protocol for the signalling step (handled by the server.py route):
  POST  /sessions/{id}/webrtc/offer  { sdp, type }  →  { sdp, type }

Limitations / future work
-------------------------
* Re-sampling is not implemented; client MUST send 16 kHz mono PCM.
* DTMF / data-channel support is not yet wired in.
* TURN server configuration should be added for NAT traversal.
"""
from __future__ import annotations

import asyncio
import fractions
import logging
from typing import AsyncGenerator

import av
import numpy as np
import structlog
from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaBlackhole
from pipecat.frames.frames import AudioRawFrame, EndFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

log: structlog.BoundLogger = structlog.get_logger(__name__)

_SAMPLE_RATE = 16_000
_CHANNELS = 1
_FRAME_SAMPLES = 320        # 20 ms at 16 kHz


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _AudioTrackReceiver(MediaStreamTrack):
    """Capture inbound WebRTC audio and expose it as an async queue of chunks."""

    kind = "audio"

    def __init__(self, track: MediaStreamTrack) -> None:
        super().__init__()
        self._track = track
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)

    async def recv(self) -> av.AudioFrame:  # type: ignore[override]
        frame: av.AudioFrame = await self._track.recv()
        pcm = frame.to_ndarray().astype(np.int16).tobytes()
        await self._queue.put(pcm)
        return frame

    async def read(self) -> bytes | None:
        return await self._queue.get()


# ---------------------------------------------------------------------------
# Transport class
# ---------------------------------------------------------------------------

class WebRTCTransport(FrameProcessor):
    """
    Pipecat ``FrameProcessor`` that bridges an ``aiortc`` ``RTCPeerConnection``
    to the rest of the pipeline.

    * **Downstream (output)**: reads audio from the inbound WebRTC track and
      pushes ``AudioRawFrame`` frames.
    * **Upstream (input)**: accepts ``AudioRawFrame`` and writes raw PCM to an
      outbound audio track sent to the peer.
    """

    def __init__(self, pc: RTCPeerConnection) -> None:
        super().__init__()
        self._pc = pc
        self._receiver: _AudioTrackReceiver | None = None
        self._send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)
        self._send_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the audio read loop once the WS transport is connected."""
        self._send_task = asyncio.create_task(
            self._drain_send_queue(), name="webrtc_send"
        )
        log.info("webrtc_transport_started")

    async def stop(self) -> None:
        if self._send_task:
            self._send_task.cancel()
            try:
                await self._send_task
            except asyncio.CancelledError:
                pass
        await self._pc.close()
        log.info("webrtc_transport_stopped")

    # ------------------------------------------------------------------
    # FrameProcessor
    # ------------------------------------------------------------------

    async def process_frame(
        self, frame: object, direction: FrameDirection
    ) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, EndFrame):
            await self.stop()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, AudioRawFrame):
            # Outbound audio — queue for sending to the peer
            await self._send_queue.put(frame.audio)
            return

        await self.push_frame(frame, direction)

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    def attach_track(self, track: MediaStreamTrack) -> None:
        """Register the inbound audio track from the RTCPeerConnection."""
        self._receiver = _AudioTrackReceiver(track)
        log.debug("webrtc_inbound_track_attached")

    async def read_frames(self) -> AsyncGenerator[AudioRawFrame, None]:
        """Yield ``AudioRawFrame`` objects from the inbound WebRTC audio."""
        if not self._receiver:
            log.warning("webrtc_no_receiver_attached")
            return
        while True:
            chunk = await self._receiver.read()
            if chunk is None:
                break
            yield AudioRawFrame(
                audio=chunk,
                sample_rate=_SAMPLE_RATE,
                num_channels=_CHANNELS,
            )

    async def _drain_send_queue(self) -> None:
        """Forward queued PCM chunks to the outbound WebRTC track (stub)."""
        while True:
            _audio_bytes = await self._send_queue.get()
            # TODO: inject into an aiortc AudioStreamTrack; requires
            # a custom MediaStreamTrack subclass that feeds av.AudioFrame.
            # For the current implementation this is a no-op placeholder.


# ---------------------------------------------------------------------------
# SDP exchange helper
# ---------------------------------------------------------------------------

async def create_answer(
    offer_sdp: str,
    offer_type: str,
    *,
    ice_servers: list[str] | None = None,
) -> tuple[RTCPeerConnection, str, str]:
    """
    Perform the SDP offer / answer exchange.

    Parameters
    ----------
    offer_sdp:
        SDP string from the browser's ``RTCPeerConnection.createOffer()``.
    offer_type:
        Typically ``"offer"``.
    ice_servers:
        Optional list of STUN/TURN URLs, e.g. ``["stun:stun.l.google.com"]``.

    Returns
    -------
    (pc, answer_sdp, answer_type)
        The configured ``RTCPeerConnection``, and the answer SDP to send back.
    """
    ice_cfg = RTCConfiguration(
        iceServers=[RTCIceServer(urls=url) for url in (ice_servers or [])]
    )
    pc = RTCPeerConnection(configuration=ice_cfg)
    pc.addTrack(MediaBlackhole())   # consume remote video track if any

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    )
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    log.info(
        "webrtc_answer_created",
        ice_servers=ice_servers,
    )
    return pc, pc.localDescription.sdp, pc.localDescription.type

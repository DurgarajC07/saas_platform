"""
WebRTC transport for the Pipeline Service.

Provides an ``aiortc``-based audio transport so that browser clients can
connect using standard WebRTC (ICE / DTLS / SRTP) instead of raw WebSocket
PCM.  This module exposes:

* ``WebRTCTransport``   — Pipecat ``FrameProcessor``; bridges an
                          ``RTCPeerConnection`` to ``AudioRawFrame`` I/O
* ``create_answer()``   — SDP offer/answer exchange helper (used by server.py)
* ``ICE_SERVERS``       — default STUN server list (override via env)

Wire protocol for the signalling step (handled by ``server.py``):
  POST  /sessions/{id}/webrtc/offer   body: {sdp, type}
                                      resp: {sdp, type}

Audio format
------------
* Inbound  (browser mic → pipeline): 16 kHz mono int16 PCM, 20 ms chunks
* Outbound (pipeline TTS → browser): 16 kHz mono int16 PCM, 20 ms chunks

ICE server strategy
-------------------
* Development / LAN: STUN-only (no relay required for same-network demos).
* Production:        Add a TURN server entry (coturn recommended) to the
                     ``ICE_SERVERS`` env-var or the ``ice_servers`` parameter.

  ICE_SERVERS=stun:stun.l.google.com:19302,turn:turn.example.com:3478?transport=udp

TURN entry format (per RTCIceServer spec):
  { "urls": "turn:...", "username": "...", "credential": "..." }
  → pass as ``RTCIceServer`` objects or configure via the pipeline service env.

Limitations
-----------
* Re-sampling is not implemented; the browser MUST negotiate 16 kHz mono.
  Set ``sampleRate: 16000`` in the browser's ``getUserMedia`` constraints.
* DTMF / data-channel support is not wired in.
"""
from __future__ import annotations

import asyncio
import contextlib
import fractions
import os
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
from pipecat.frames.frames import AudioRawFrame, EndFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

log: structlog.BoundLogger = structlog.get_logger(__name__)

# ── Audio constants ───────────────────────────────────────────────────────────
_SAMPLE_RATE:    int = 16_000
_CHANNELS:       int = 1
_FRAME_SAMPLES:  int = 320       # 20 ms at 16 kHz  (320 samples × 2 bytes = 640 B)
_TIME_BASE           = fractions.Fraction(1, _SAMPLE_RATE)

# ── Default ICE servers ───────────────────────────────────────────────────────
# Override per-deployment with ICE_SERVERS env-var (comma-separated STUN/TURN URLs).
# TURN entries that need credentials must be passed programmatically via ice_servers=.
_DEFAULT_ICE_STUN = "stun:stun.l.google.com:19302"
ICE_SERVERS: list[str] = [
    url.strip()
    for url in os.getenv("ICE_SERVERS", _DEFAULT_ICE_STUN).split(",")
    if url.strip()
]


# ── ICE server dict format sent to browsers ───────────────────────────────────

def ice_servers_for_client(
    extra: list[dict] | None = None,
) -> list[dict]:
    """
    Return a JSON-serialisable ICE server list for the browser SDK.

    Parameters
    ----------
    extra:
        Optional additional entries (e.g. TURN with credentials) as dicts
        matching the ``RTCIceServer`` dict shape:
        ``{"urls": "turn:...", "username": "...", "credential": "..."}``.
    """
    servers: list[dict] = [{"urls": url} for url in ICE_SERVERS]
    if extra:
        servers.extend(extra)
    return servers


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _InboundAudioReceiver:
    """
    Wraps an inbound ``MediaStreamTrack`` and buffers decoded PCM into a queue.

    ``recv()`` on the underlying track is called in a background asyncio task;
    decoded int16 bytes are placed in an internal ``asyncio.Queue``.  This
    decouples the aiortc internals from the Pipecat frame loop.
    """

    def __init__(
        self, track: MediaStreamTrack, sample_rate: int = _SAMPLE_RATE
    ) -> None:
        self._track = track
        self._sample_rate = sample_rate
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._read_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._queue.put(None)   # unblock any waiting consumer

    async def _read_loop(self) -> None:
        try:
            while True:
                frame: av.AudioFrame = await self._track.recv()
                # Normalise to int16 mono regardless of what the browser sent
                arr = frame.to_ndarray()
                if arr.dtype != np.int16:
                    arr = (arr * 32767).astype(np.int16)
                if arr.ndim > 1:
                    arr = arr[0]                 # take first channel (mono)
                await self._queue.put(arr.tobytes())
        except (asyncio.CancelledError, Exception):
            await self._queue.put(None)

    async def read(self) -> bytes | None:
        """Return the next PCM chunk or ``None`` when the track has ended."""
        return await self._queue.get()


class _OutboundAudioTrack(MediaStreamTrack):
    """
    Custom ``MediaStreamTrack`` that feeds int16 PCM bytes from an asyncio
    queue into the WebRTC send path as ``av.AudioFrame`` objects.

    The browser receives standard Opus-encoded audio; the ``aiortc`` layer
    handles the PCM → Opus encoding automatically.
    """

    kind = "audio"

    def __init__(
        self,
        queue: asyncio.Queue[bytes],
        sample_rate: int = _SAMPLE_RATE,
        frame_samples: int = _FRAME_SAMPLES,
    ) -> None:
        super().__init__()
        self._queue = queue
        self._sample_rate = sample_rate
        self._frame_samples = frame_samples
        self._pts: int = 0
        self._time_base = fractions.Fraction(1, sample_rate)
        self._buf = b""        # partial-frame accumulation buffer

    async def recv(self) -> av.AudioFrame:
        """
        Block until we have enough PCM bytes for one frame, then return an
        ``av.AudioFrame``.  Small queue chunks are accumulated; large chunks
        are split across calls.
        """
        needed = self._frame_samples * 2  # bytes at int16
        while len(self._buf) < needed:
            chunk = await self._queue.get()
            self._buf += chunk

        pcm, self._buf = self._buf[:needed], self._buf[needed:]
        samples = np.frombuffer(pcm, dtype=np.int16).reshape(1, -1)

        frame = av.AudioFrame.from_ndarray(samples, format="s16p", layout="mono")
        frame.sample_rate = self._sample_rate
        frame.pts = self._pts
        frame.time_base = self._time_base
        self._pts += self._frame_samples
        return frame


# ---------------------------------------------------------------------------
# Transport class
# ---------------------------------------------------------------------------

class WebRTCTransport(FrameProcessor):
    """
    Pipecat ``FrameProcessor`` that bridges an ``aiortc`` ``RTCPeerConnection``
    to the rest of the pipeline.

    Inbound (browser mic → pipeline)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    The ``on_track`` callback on the ``RTCPeerConnection`` calls
    ``attach_track()``.  Decoded PCM bytes flow through
    ``_InboundAudioReceiver`` and are yielded as ``AudioRawFrame`` objects by
    ``read_frames()``.  The pipeline's frame-ingestion task should call
    ``read_frames()`` in an async loop and push each frame to
    ``process_frame``.

    Outbound (pipeline TTS → browser)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``process_frame`` intercepts ``AudioRawFrame`` objects flowing upstream
    and puts raw PCM bytes into ``_send_queue``.  The ``_OutboundAudioTrack``
    picks them up and converts them to ``av.AudioFrame`` for aiortc / Opus
    encoding.

    Parameters
    ----------
    pc:
        A configured ``RTCPeerConnection`` (created by ``create_answer()``).
    """

    def __init__(self, pc: RTCPeerConnection) -> None:
        super().__init__()
        self._pc = pc
        self._receiver: _InboundAudioReceiver | None = None
        self._send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)
        self._outbound_track = _OutboundAudioTrack(self._send_queue)
        self._pc.addTrack(self._outbound_track)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        log.info("webrtc_transport.started")

    async def stop(self) -> None:
        if self._receiver:
            await self._receiver.stop()
        try:
            await self._pc.close()
        except Exception:
            pass
        log.info("webrtc_transport.stopped")

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

        if isinstance(frame, AudioRawFrame) and direction == FrameDirection.UPSTREAM:
            # Outbound TTS audio — queue for aiortc → Opus send
            try:
                self._send_queue.put_nowait(frame.audio)
            except asyncio.QueueFull:
                log.warning("webrtc_transport.send_queue_full")
            return

        await self.push_frame(frame, direction)

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    def attach_track(self, track: MediaStreamTrack) -> None:
        """Register the inbound audio track received from the browser."""
        self._receiver = _InboundAudioReceiver(track, sample_rate=_SAMPLE_RATE)
        self._receiver.start()
        log.debug("webrtc_transport.inbound_track_attached", kind=track.kind)

    async def read_frames(self) -> AsyncGenerator[AudioRawFrame, None]:
        """
        Yield ``AudioRawFrame`` instances decoded from the inbound WebRTC audio.

        Stops when the remote track ends (``read()`` returns ``None``).
        """
        if not self._receiver:
            log.warning("webrtc_transport.no_receiver_attached")
            return
        while True:
            chunk = await self._receiver.read()
            if chunk is None:
                return
            yield AudioRawFrame(
                audio=chunk,
                sample_rate=_SAMPLE_RATE,
                num_channels=_CHANNELS,
            )

    # ------------------------------------------------------------------
    # Pipecat transport duck-type compatibility
    # ------------------------------------------------------------------

    def input(self) -> "WebRTCInputProcessor":  # noqa: A003
        """
        Return a ``FrameProcessor`` that feeds inbound WebRTC audio into the
        Pipecat pipeline.  Mirrors the ``FastAPIWebsocketTransport.input()``
        API so ``PipelineBuilder.build()`` can accept a ``WebRTCTransport``
        via duck typing.
        """
        return WebRTCInputProcessor(self)

    def output(self) -> "WebRTCTransport":  # noqa: A003
        """
        Return *self* as the pipeline output sink.  ``process_frame`` already
        handles upstream ``AudioRawFrame`` objects (TTS → WebRTC) so no
        additional wrapper is needed.
        """
        return self


# ---------------------------------------------------------------------------
# Pipeline source adapter
# ---------------------------------------------------------------------------

class WebRTCInputProcessor(FrameProcessor):
    """
    Pipecat ``FrameProcessor`` that bridges a ``WebRTCTransport``'s inbound
    audio into the pipeline.

    Placed first in a ``Pipeline`` processors list this acts as the frame
    source: a background asyncio task reads ``AudioRawFrame`` objects from
    ``WebRTCTransport.read_frames()`` and pushes them downstream.  When the
    inbound track ends an ``EndFrame`` is pushed to signal EOF to the pipeline.

    Usage::

        transport = WebRTCTransport(pc)
        pipeline = Pipeline([transport.input(), ..., transport.output()])
    """

    def __init__(self, transport: WebRTCTransport) -> None:
        super().__init__()
        self._transport = transport
        self._feed_task: asyncio.Task | None = None

    async def start(self, settings: object = None) -> None:  # type: ignore[override]
        """Start the background frame-feeding task."""
        # Call super with or without settings depending on pipecat version
        try:
            await super().start(settings)  # type: ignore[arg-type]
        except TypeError:
            await super().start()  # type: ignore[call-arg]
        self._feed_task = asyncio.create_task(
            self._feed(), name="webrtc_input_feed"
        )

    async def stop(self, event: object = None) -> None:  # type: ignore[override]
        """Cancel the feeding task."""
        if self._feed_task and not self._feed_task.done():
            self._feed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._feed_task
        try:
            await super().stop(event)  # type: ignore[arg-type]
        except TypeError:
            await super().stop()  # type: ignore[call-arg]

    async def process_frame(  # type: ignore[override]
        self, frame: object, direction: FrameDirection
    ) -> None:
        """Pass non-audio frames through unchanged."""
        await super().process_frame(frame, direction)  # type: ignore[arg-type]
        await self.push_frame(frame, direction)  # type: ignore[arg-type]

    # ------------------------------------------------------------------

    async def _feed(self) -> None:
        """
        Background task: drains ``WebRTCTransport.read_frames()`` and pushes
        each chunk downstream as an ``AudioRawFrame``.
        """
        try:
            async for audio_frame in self._transport.read_frames():
                await self.push_frame(audio_frame, FrameDirection.DOWNSTREAM)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("webrtc_input_feed_error", error=str(exc), exc_info=True)
        finally:
            # Signal pipeline EOF
            await self.push_frame(EndFrame(), FrameDirection.DOWNSTREAM)


# ---------------------------------------------------------------------------
# SDP exchange helper
# ---------------------------------------------------------------------------

async def create_answer(
    offer_sdp: str,
    offer_type: str = "offer",
    *,
    ice_servers: list[str] | None = None,
    ice_timeout_s: float = 5.0,
) -> tuple[RTCPeerConnection, str, str]:
    """
    Perform the SDP offer / answer exchange and wait for ICE gathering.

    Parameters
    ----------
    offer_sdp:
        SDP string from the browser's ``RTCPeerConnection.createOffer()``.
    offer_type:
        Typically ``"offer"``; defaults to ``"offer"``.
    ice_servers:
        Override list of STUN/TURN URLs.  ``None`` uses ``ICE_SERVERS``.
    ice_timeout_s:
        Seconds to wait for ICE gathering to complete before returning the
        partial candidate list.  5 s is enough for most STUN scenarios.

    Returns
    -------
    (pc, answer_sdp, answer_type)
        The configured peer connection, and the answer SDP to send back.
    """
    servers = ice_servers if ice_servers is not None else ICE_SERVERS
    ice_cfg = RTCConfiguration(
        iceServers=[RTCIceServer(urls=url) for url in servers]
    )
    pc = RTCPeerConnection(configuration=ice_cfg)

    # Wait-until-gathered event
    _gathered = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def _on_gathering():
        if pc.iceGatheringState == "complete":
            _gathered.set()

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    )
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    # Allow ICE candidates to be gathered; continue after timeout
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(_gathered.wait(), timeout=ice_timeout_s)

    log.info(
        "webrtc.answer_created",
        ice_servers=servers,
        gathering_state=pc.iceGatheringState,
    )
    return pc, pc.localDescription.sdp, pc.localDescription.type

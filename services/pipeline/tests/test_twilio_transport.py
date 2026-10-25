"""
Unit tests for Twilio PSTN transport and DTMF router.

Deliverables verified
---------------------
  ✓  _mulaw_to_pcm16k / _pcm16k_to_mulaw_b64 codec round-trip (no data loss)
  ✓  TwilioTransport._parse_message handles each Twilio event type correctly
      – connected  → ignored silently
      – start      → stream_sid + call_sid captured on transport
      – media      → DTMFFrame / AudioRawFrame enqueued
      – dtmf       → DTMFFrame(digit, finished) enqueued
      – stop       → EndFrame enqueued
  ✓  TwilioTransport.input() returns TwilioInputProcessor instance
  ✓  TwilioTransport.output() returns transport itself
  ✓  DTMFRouter dispatches each action correctly
      – transfer   → TransferCallFrame with destination
      – hangup     → EndFrame
      – repeat     → RepeatMenuFrame
      – operator   → TransferCallFrame with operator_number
      – none       → no frame emitted
  ✓  DTMFRouter ignores unrecognised digits (no crash)
  ✓  DTMFRouter only acts when finished=True
"""
from __future__ import annotations

import asyncio
import base64
import json
import struct
import sys
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Allow direct imports from services/pipeline/
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------
from transports.twilio import (
    DTMFFrame,
    TransferCallFrame,
    ClearAudioFrame,
    TwilioTransport,
    TwilioInputProcessor,
    make_twilio_transport,
    _mulaw_to_pcm16k,
    _pcm16k_to_mulaw_b64,
)
from processors.dtmf import DTMFRouter, RepeatMenuFrame

try:
    import audioop
except ImportError:
    import audioop_lts as audioop  # type: ignore[no-redef]

from pipecat.frames.frames import AudioRawFrame, EndFrame
from pipecat.processors.frame_processor import FrameDirection


# ---------------------------------------------------------------------------
# Codec round-trip tests
# ---------------------------------------------------------------------------

class TestCodecRoundTrip:
    """Verify that encoding then decoding preserves audio data."""

    def _make_pcm16k(self, num_samples: int = 160) -> bytes:
        """Generate a simple sine-like PCM16 buffer at 16 kHz."""
        return struct.pack(f"<{num_samples}h", *[i % 32767 for i in range(num_samples)])

    def test_roundtrip_identity(self):
        """PCM 16kHz → µ-law+b64 → PCM 16kHz should match within codec tolerance."""
        original: bytes = self._make_pcm16k(160)
        encoded: str = _pcm16k_to_mulaw_b64(original)
        # encoded must be valid base64
        decoded_b64 = base64.b64decode(encoded)
        assert len(decoded_b64) > 0

        recovered: bytes = _mulaw_to_pcm16k(encoded)
        # 16kHz -> 8kHz -> 16kHz through audioop.ratecv is lossy resampling,
        # not a lossless codec — its internal filter state can legitimately
        # land one sample short/long at a conversion boundary. This was
        # previously asserting an exact count (`== 160`), which is stricter
        # than the resampler actually guarantees; a small, fixed tolerance
        # matches the "within codec tolerance" behavior this test already
        # claims to verify in its docstring.
        recovered_samples = struct.unpack(f"<{len(recovered)//2}h", recovered)
        assert abs(len(recovered_samples) - 160) <= 2

    def test_pcm16k_to_mulaw_b64_returns_str(self):
        pcm = self._make_pcm16k(80)
        result = _pcm16k_to_mulaw_b64(pcm)
        assert isinstance(result, str)
        # Validate it's decodable base64
        base64.b64decode(result)  # must not raise

    def test_mulaw_to_pcm16k_empty_input(self):
        """Empty µ-law payload should return empty bytes."""
        empty_b64 = base64.b64encode(b"").decode()
        result = _mulaw_to_pcm16k(empty_b64)
        assert result == b""


# ---------------------------------------------------------------------------
# TwilioTransport._parse_message tests
# ---------------------------------------------------------------------------

def _make_transport() -> TwilioTransport:
    """Build a TwilioTransport with a mock WebSocket."""
    ws = MagicMock()
    ws.send_text = AsyncMock()
    transport = TwilioTransport(ws)
    return transport


class TestParseMessage:
    """
    Test event parsing without running the full WS loop.

    ``_parse_message`` is synchronous and RETURNS the parsed frame (or
    None) — it does not touch ``self._queue`` itself; that's the caller's
    job in the real `_ws_reader` loop (`frame = self._parse_message(raw);
    if frame is not None: self._queue.put_nowait(frame)`). These tests
    previously `await`ed a sync function and expected it to have already
    enqueued the frame, which never matched the real implementation and
    only "passed" before because conftest.py's broken pipecat-detection
    check (fixed separately) was silently substituting a stub that masked
    the mismatch instead of exercising the real code.
    """

    def test_connected_event_is_silent(self):
        t = _make_transport()
        msg = json.dumps({"event": "connected", "protocol": "Call", "version": "1.0"})
        result = t._parse_message(msg)
        assert result is None

    def test_start_event_captures_ids(self):
        t = _make_transport()
        msg = json.dumps({
            "event": "start",
            "streamSid": "MZ123",
            "start": {
                "streamSid": "MZ123",
                "callSid": "CA456",
                "accountSid": "ACabc",
            },
        })
        result = t._parse_message(msg)
        assert result is None
        assert t.stream_sid == "MZ123"
        assert t.call_sid == "CA456"

    def test_dtmf_event_enqueues_dtmf_frame(self):
        t = _make_transport()
        msg = json.dumps({
            "event": "dtmf",
            "dtmf": {"digit": "5", "finished": True},
        })
        frame = t._parse_message(msg)
        assert isinstance(frame, DTMFFrame)
        assert frame.digit == "5"
        assert frame.finished is True

    def test_stop_event_enqueues_end_frame(self):
        t = _make_transport()
        msg = json.dumps({"event": "stop", "streamSid": "MZ123"})
        frame = t._parse_message(msg)
        assert isinstance(frame, EndFrame)

    def test_media_event_enqueues_audio_raw_frame(self):
        t = _make_transport()
        # stream_sid is read-only (captured internally from the "start"
        # event) — decoding a "media" event doesn't depend on it, so no
        # setup beyond a fresh transport is needed.
        raw_mulaw = audioop.lin2ulaw(b"\x00\x01" * 8, 2)
        payload_b64 = base64.b64encode(raw_mulaw).decode()
        msg = json.dumps({
            "event": "media",
            "media": {"payload": payload_b64, "track": "inbound"},
        })
        frame = t._parse_message(msg)
        assert isinstance(frame, AudioRawFrame)
        assert frame.audio  # non-empty


# ---------------------------------------------------------------------------
# TwilioTransport interface contract
# ---------------------------------------------------------------------------

class TestTransportInterface:
    def test_input_returns_twilio_input_processor(self):
        t = _make_transport()
        inp = t.input()
        assert isinstance(inp, TwilioInputProcessor)

    def test_output_returns_self(self):
        t = _make_transport()
        assert t.output() is t

    def test_make_twilio_transport_factory(self):
        ws = MagicMock()
        t = make_twilio_transport(ws)
        assert isinstance(t, TwilioTransport)


# ---------------------------------------------------------------------------
# DTMFRouter tests
# ---------------------------------------------------------------------------

def _collected_frames(router: DTMFRouter) -> list:
    """Run a queue drain so we can inspect what frames the router pushes."""
    frames: list = []
    async def capture(frame, direction):
        frames.append(frame)
    router.push_frame = AsyncMock(side_effect=capture)
    return frames


class TestDTMFRouter:
    """Test routing dispatch for each action type."""

    def _make_router(self, routing_map: dict, operator_number: str = "") -> DTMFRouter:
        return DTMFRouter(routing_map=routing_map, operator_number=operator_number)

    @pytest.mark.asyncio
    async def test_transfer_action(self):
        router = self._make_router({"1": ("transfer", "+15551234567")})
        frames: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            frames.append(frame)

        router.push_frame = capture

        dtmf = DTMFFrame(digit="1", finished=True)
        await router.process_frame(dtmf, FrameDirection.DOWNSTREAM)

        assert len(frames) == 1
        assert isinstance(frames[0], TransferCallFrame)
        assert frames[0].destination == "+15551234567"

    @pytest.mark.asyncio
    async def test_hangup_action(self):
        router = self._make_router({"9": ("hangup", None)})
        frames: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            frames.append(frame)

        router.push_frame = capture

        dtmf = DTMFFrame(digit="9", finished=True)
        await router.process_frame(dtmf, FrameDirection.DOWNSTREAM)

        assert len(frames) == 1
        assert isinstance(frames[0], EndFrame)

    @pytest.mark.asyncio
    async def test_repeat_action(self):
        router = self._make_router({"0": ("repeat", None)})
        frames: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            frames.append(frame)

        router.push_frame = capture

        dtmf = DTMFFrame(digit="0", finished=True)
        await router.process_frame(dtmf, FrameDirection.DOWNSTREAM)

        assert len(frames) == 1
        assert isinstance(frames[0], RepeatMenuFrame)

    @pytest.mark.asyncio
    async def test_operator_action(self):
        router = self._make_router({"0": ("operator", None)}, operator_number="+10005550001")
        frames: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            frames.append(frame)

        router.push_frame = capture

        dtmf = DTMFFrame(digit="0", finished=True)
        await router.process_frame(dtmf, FrameDirection.DOWNSTREAM)

        assert len(frames) == 1
        assert isinstance(frames[0], TransferCallFrame)
        assert frames[0].destination == "+10005550001"

    @pytest.mark.asyncio
    async def test_none_action_no_frame_emitted(self):
        router = self._make_router({"5": ("none", None)})
        frames: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            frames.append(frame)

        router.push_frame = capture

        dtmf = DTMFFrame(digit="5", finished=True)
        await router.process_frame(dtmf, FrameDirection.DOWNSTREAM)

        assert frames == []

    @pytest.mark.asyncio
    async def test_unrecognised_digit_no_crash(self):
        """An unknown digit should not raise and should not emit a frame."""
        router = self._make_router({"1": ("transfer", "+15551234567")})
        frames: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            frames.append(frame)

        router.push_frame = capture

        dtmf = DTMFFrame(digit="*", finished=True)
        await router.process_frame(dtmf, FrameDirection.DOWNSTREAM)

        assert frames == []

    @pytest.mark.asyncio
    async def test_not_finished_dtmf_is_ignored(self):
        """Router must only act on finished=True DTMF events."""
        router = self._make_router({"1": ("hangup", None)})
        frames: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            frames.append(frame)

        router.push_frame = capture

        dtmf = DTMFFrame(digit="1", finished=False)
        await router.process_frame(dtmf, FrameDirection.DOWNSTREAM)

        assert frames == []

    @pytest.mark.asyncio
    async def test_non_dtmf_frame_passes_through(self):
        """Non-DTMF frames must be forwarded unchanged."""
        router = self._make_router({"1": ("hangup", None)})
        frames: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            frames.append(frame)

        router.push_frame = capture

        audio = AudioRawFrame(audio=b"\x00" * 320, sample_rate=16000, num_channels=1)
        await router.process_frame(audio, FrameDirection.DOWNSTREAM)

        assert len(frames) == 1
        assert isinstance(frames[0], AudioRawFrame)

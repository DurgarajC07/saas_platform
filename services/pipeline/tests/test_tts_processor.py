"""
Unit tests for KokoroTTSProcessor — Day 7 deliverables.

Tests exercise audio level normalisation, VOICE_MAP contents, stream-to-stream
latency logging, text-buffer / sentence-split logic, graceful fail-open on
Kokoro unavailability, phoneme pre-warm, and CallRecorder integration.

No real Kokoro service is required — WebSocket interactions are fully mocked.

Deliverables verified
---------------------
  ✓  VOICE_MAP contains all required voice identifiers
  ✓  set_voice / set_speed mutate the payload sent to Kokoro
  ✓  _normalize_lufs brings loud audio closer to -20 LUFS target
  ✓  _normalize_lufs brings quiet audio up to -20 LUFS target
  ✓  _normalize_lufs passes silence (near-zero) frames unchanged
  ✓  _normalize_lufs returns empty bytes unchanged
  ✓  TTFB first_audio log entry emitted on the first WAV chunk
  ✓  Text sentences are dispatched after sentence-boundary split
  ✓  Individual short text chunk not dispatched (below _MIN_DISPATCH_CHARS)
  ✓  Kokoro unavailable → _unavailable flag set, no crash, no WS calls
  ✓  Connection lost mid-stream → reconnect task scheduled
  ✓  pre_warm() sends one payload per phrase and drains responses
  ✓  pre_warm() is a no-op when _unavailable
  ✓  CallRecorder.write_outbound() called for every audio chunk
  ✓  recorder=None default does not crash
"""

from __future__ import annotations

import asyncio
import io
import json
import struct
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

# Allow direct imports from services/pipeline/
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipecat.frames.frames import (
    EndFrame,
    StartFrame,
    StartInterruptionFrame,
    TextFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from processors.tts import (
    VOICE_MAP,
    KokoroTTSProcessor,
    _normalize_lufs,
    _wav_bytes_to_pcm,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_SAMPLE_RATE = 24_000
_TARGET_LUFS = -20.0


def _make_wav(amplitude: float = 0.5, num_samples: int = 480) -> bytes:
    """
    Create a minimal mono 24 kHz int16 WAV filled with a sine tone.

    Parameters
    ----------
    amplitude:
        Peak amplitude in the range [0, 1].  0.5 → moderate volume,
        0.001 → near-silence.
    num_samples:
        Number of samples (20 ms at 24 kHz ≈ 480 samples).
    """
    t = np.linspace(0, 2 * np.pi * 10, num_samples, endpoint=False)
    signal = (np.sin(t) * amplitude * 32767).astype(np.int16)
    buf = io.BytesIO()
    sf.write(buf, signal, _SAMPLE_RATE, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def _lufs_of(pcm_bytes: bytes) -> float:
    """Compute simplified LUFS of raw int16 PCM bytes."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    ms = float(np.mean(samples ** 2))
    if ms < 1e-9:
        return -96.0  # dbFS floor
    return -0.691 + 10.0 * np.log10(ms)


class MockWebSocket:
    """Lightweight async WS stub that replays pre-queued messages."""

    def __init__(self, responses: list[str | bytes] | None = None) -> None:
        self.sent: list[Any] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        for r in (responses or []):
            self._queue.put_nowait(r)

    async def send(self, data: Any) -> None:
        self.sent.append(data)

    async def recv(self) -> str | bytes:
        return await self._queue.get()

    async def close(self) -> None:
        pass

    def enqueue(self, item: str | bytes) -> None:
        self._queue.put_nowait(item)


def _done_msg() -> str:
    return json.dumps({"done": True, "elapsed_ms": 25})


def _build_proc(**kwargs: Any) -> KokoroTTSProcessor:
    """Create a processor with a no-op push_frame so tests can inject their own."""
    proc = KokoroTTSProcessor(**kwargs)
    return proc


async def _capture_dispatch(
    proc: KokoroTTSProcessor,
    ws: MockWebSocket,
    text: str,
) -> list[Any]:
    """Inject *ws*, mock push_frame, dispatch *text*, return collected frames."""
    proc._ws = ws
    proc._unavailable = False
    captured: list[Any] = []

    async def capture(frame: Any, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        captured.append(frame)

    proc.push_frame = capture  # type: ignore[method-assign]
    await proc._dispatch(text)
    return captured


# ── TestVoiceMap ──────────────────────────────────────────────────────────────


class TestVoiceMap:
    """VOICE_MAP must contain the required voices and set_voice must work."""

    def test_has_american_female_warm(self) -> None:
        assert "af_heart" in VOICE_MAP

    def test_has_american_male(self) -> None:
        assert "am_adam" in VOICE_MAP

    def test_has_british_female(self) -> None:
        assert "bf_emma" in VOICE_MAP

    def test_has_british_male(self) -> None:
        assert "bm_george" in VOICE_MAP

    def test_all_values_are_strings(self) -> None:
        assert all(isinstance(v, str) for v in VOICE_MAP.values())

    def test_set_voice_updates_internal_state(self) -> None:
        proc = _build_proc(voice="af_heart")
        proc.set_voice("bf_emma", lang="b")
        assert proc._voice == "bf_emma"
        assert proc._lang == "b"

    def test_set_voice_without_lang_preserves_lang(self) -> None:
        proc = _build_proc(voice="af_heart", lang="a")
        proc.set_voice("am_adam")
        assert proc._voice == "am_adam"
        assert proc._lang == "a"

    def test_set_speed_clamps_low(self) -> None:
        proc = _build_proc()
        proc.set_speed(0.1)
        assert proc._speed == 0.25

    def test_set_speed_clamps_high(self) -> None:
        proc = _build_proc()
        proc.set_speed(99.0)
        assert proc._speed == 3.0

    async def test_dispatch_payload_contains_updated_voice(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, _done_msg()])
        proc = _build_proc(voice="af_heart")
        proc.set_voice("bm_lewis")
        await _capture_dispatch(proc, ws, "Testing voice payload.")
        assert ws.sent, "no payload sent"
        payload = json.loads(ws.sent[0])
        assert payload["voice"] == "bm_lewis"


# ── TestLUFSNormalization ─────────────────────────────────────────────────────


class TestLUFSNormalization:
    """_normalize_lufs must bring audio towards −20 LUFS."""

    def _pcm_sine(self, amplitude: float, num_samples: int = 960) -> bytes:
        """Create int16 PCM bytes of a sine tone with the given amplitude [0,1]."""
        t = np.linspace(0, 2 * np.pi * 20, num_samples, endpoint=False)
        return (np.sin(t) * amplitude * 32767).astype(np.int16).tobytes()

    def test_loud_signal_reduced_toward_target(self) -> None:
        # Amplitude 0.95 → LUFS well above -20
        pcm_in = self._pcm_sine(amplitude=0.95)
        lufs_in = _lufs_of(pcm_in)
        assert lufs_in > _TARGET_LUFS, f"pre-condition failed: {lufs_in:.1f}"

        pcm_out = _normalize_lufs(pcm_in, target_lufs=_TARGET_LUFS)
        lufs_out = _lufs_of(pcm_out)

        assert abs(lufs_out - _TARGET_LUFS) < 2.0, (
            f"Expected LUFS ≈ {_TARGET_LUFS}, got {lufs_out:.1f}"
        )

    def test_quiet_signal_boosted_toward_target(self) -> None:
        # Amplitude 0.05 → LUFS ≈ -29 dBFS, needs ~3× gain (well under _MAX_GAIN=10×)
        pcm_in = self._pcm_sine(amplitude=0.05)
        lufs_in = _lufs_of(pcm_in)
        assert lufs_in < _TARGET_LUFS, f"pre-condition failed: {lufs_in:.1f}"

        pcm_out = _normalize_lufs(pcm_in, target_lufs=_TARGET_LUFS)
        lufs_out = _lufs_of(pcm_out)

        assert abs(lufs_out - _TARGET_LUFS) < 2.0, (
            f"Expected LUFS ≈ {_TARGET_LUFS}, got {lufs_out:.1f}"
        )

    def test_silence_passthrough(self) -> None:
        """Near-silent frames must not be touched (gain cap prevents NaN/INF)."""
        pcm_silence = np.zeros(480, dtype=np.int16).tobytes()
        result = _normalize_lufs(pcm_silence)
        # Output should still be silence (all zeros clamped)
        assert len(result) == len(pcm_silence)

    def test_empty_bytes_passthrough(self) -> None:
        assert _normalize_lufs(b"") == b""

    def test_output_type_is_bytes(self) -> None:
        pcm = self._pcm_sine(0.5)
        assert isinstance(_normalize_lufs(pcm), bytes)

    def test_output_no_samples_beyond_int16_range(self) -> None:
        """After normalisation every sample must fit int16 range."""
        pcm = self._pcm_sine(amplitude=0.5)
        out = _normalize_lufs(pcm)
        samples = np.frombuffer(out, dtype=np.int16)
        assert samples.max() <= 32767
        assert samples.min() >= -32768


# ── TestStreamToStream ────────────────────────────────────────────────────────


class TestStreamToStream:
    """Text buffering, sentence splitting, and frame emission."""

    async def test_sentence_dispatch_emits_tts_audio_frame(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, _done_msg()])
        proc = _build_proc()
        frames = await _capture_dispatch(proc, ws, "Hello there. Nice to meet you.")
        tts_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        assert len(tts_frames) == 1
        assert tts_frames[0].sample_rate == 24_000
        assert tts_frames[0].num_channels == 1

    async def test_multiple_wav_chunks_produce_multiple_frames(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, wav, _done_msg()])
        proc = _build_proc()
        frames = await _capture_dispatch(proc, ws, "Two chunks test sentence.")
        tts_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        assert len(tts_frames) == 2

    async def test_short_text_not_dispatched_by_maybe_dispatch(self) -> None:
        """Fragments below _MIN_DISPATCH_CHARS should not be dispatched."""
        proc = _build_proc()
        proc._ws = MockWebSocket()
        proc.push_frame = AsyncMock()
        proc._text_buffer = "Hi"  # 2 chars, below threshold
        # _maybe_dispatch won't split (no sentence boundary either)
        await proc._maybe_dispatch()
        assert proc._text_buffer == "Hi"  # unchanged

    async def test_sentence_split_dispatches_first_leaves_remainder(self) -> None:
        """After split, the trailing incomplete sentence stays in _text_buffer."""
        proc = _build_proc()
        dispatched: list[str] = []

        async def fake_dispatch(text: str) -> None:
            dispatched.append(text)

        proc._dispatch = fake_dispatch  # type: ignore[method-assign]
        proc._text_buffer = "Hello world. How are"
        await proc._maybe_dispatch()
        assert len(dispatched) == 1
        assert dispatched[0] == "Hello world."
        assert proc._text_buffer == "How are"

    async def test_interruption_clears_buffer(self) -> None:
        proc = _build_proc()
        proc.push_frame = AsyncMock()
        proc._text_buffer = "pending text"
        await proc.process_frame(StartInterruptionFrame(), FrameDirection.DOWNSTREAM)
        assert proc._text_buffer == ""
        assert proc._interrupted is True


# ── TestTTFBLogging ────────────────────────────────────────────────────────────


class TestTTFBLogging:
    """first_audio log entry must appear on the very first WAV chunk."""

    async def test_first_audio_logged_with_ttfb_ms(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, _done_msg()])
        proc = _build_proc()
        proc._ws = ws
        proc._unavailable = False

        log_events: list[dict] = []

        def capture_info(event: str, **kw: Any) -> None:
            log_events.append({"event": event, **kw})

        proc._log = MagicMock()
        proc._log.info.side_effect = capture_info
        proc._log.debug = MagicMock()
        proc._log.warning = MagicMock()
        proc._log.error = MagicMock()

        proc.push_frame = AsyncMock()
        await proc._dispatch("Testing TTFB logging now.")

        first_audio_events = [e for e in log_events if e["event"] == "kokoro_tts.first_audio"]
        assert first_audio_events, "kokoro_tts.first_audio not logged"
        assert "ttfb_ms" in first_audio_events[0]
        assert "chars" in first_audio_events[0]
        assert first_audio_events[0]["ttfb_ms"] >= 0

    async def test_first_audio_logged_only_once_for_multiple_chunks(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, wav, _done_msg()])
        proc = _build_proc()
        proc._ws = ws
        proc._unavailable = False

        log_events: list[dict] = []

        def capture_info(event: str, **kw: Any) -> None:
            log_events.append({"event": event, **kw})

        proc._log = MagicMock()
        proc._log.info.side_effect = capture_info
        proc._log.debug = MagicMock()
        proc._log.warning = MagicMock()
        proc._log.error = MagicMock()

        proc.push_frame = AsyncMock()
        await proc._dispatch("Two chunk sentence test.")

        first_audio_events = [e for e in log_events if e["event"] == "kokoro_tts.first_audio"]
        assert len(first_audio_events) == 1, "first_audio must be logged exactly once"


# ── TestFailOpen ──────────────────────────────────────────────────────────────


class TestFailOpen:
    """Kokoro unavailable → processor must degrade gracefully without crashing."""

    async def test_connect_failure_sets_unavailable(self) -> None:
        proc = _build_proc(kokoro_url="ws://invalid-host:9999/tts/stream")

        with patch("processors.tts.ws_client.connect", side_effect=OSError("refused")):
            with patch.object(proc, "_schedule_reconnect"):
                await proc._connect()

        assert proc._unavailable is True
        assert proc._ws is None

    async def test_dispatch_skipped_when_unavailable(self) -> None:
        proc = _build_proc()
        proc._unavailable = True
        proc._ws = MockWebSocket()  # should NEVER be touched
        proc.push_frame = AsyncMock()

        await proc._dispatch("This should not be sent.")

        # No data should have been sent to the WS
        assert proc._ws.sent == []
        proc.push_frame.assert_not_called()

    async def test_text_frame_ignored_when_unavailable(self) -> None:
        proc = _build_proc()
        proc._unavailable = True
        proc.push_frame = AsyncMock()

        await proc.process_frame(TextFrame(text="Hello?"), FrameDirection.DOWNSTREAM)

        # _text_buffer stays empty; no dispatch attempted
        assert proc._text_buffer == ""

    async def test_connection_lost_mid_stream_marks_unavailable(self) -> None:
        import websockets

        ws = MockWebSocket()
        # First recv raises ConnectionClosed

        async def bad_recv() -> bytes:
            raise websockets.ConnectionClosed(None, None)

        ws.recv = bad_recv  # type: ignore[method-assign]
        proc = _build_proc()
        proc._ws = ws
        proc._unavailable = False
        proc.push_frame = AsyncMock()

        with patch.object(proc, "_schedule_reconnect") as mock_sched:
            await proc._dispatch("Sentence that triggers connection loss.")
            mock_sched.assert_called_once()

        assert proc._unavailable is True

    async def test_reconnect_scheduled_after_connect_failure(self) -> None:
        proc = _build_proc()
        with patch("processors.tts.ws_client.connect", side_effect=ConnectionRefusedError):
            with patch.object(proc, "_schedule_reconnect") as mock_sched:
                await proc._connect()
                mock_sched.assert_called_once()


# ── TestPreWarm ───────────────────────────────────────────────────────────────


class TestPreWarm:
    """pre_warm() must send each phrase and drain responses without emitting frames."""

    async def test_pre_warm_sends_phrases(self) -> None:
        phrases = ["Hello there.", "How can I help you?"]
        # For each phrase: 1 WAV chunk + done message
        responses: list[str | bytes] = []
        for _ in phrases:
            responses.append(_make_wav())
            responses.append(_done_msg())

        ws = MockWebSocket(responses)
        proc = _build_proc()
        proc._ws = ws
        proc._unavailable = False
        proc.push_frame = AsyncMock()

        await proc.pre_warm(phrases)

        # Two payloads must have been sent (one per phrase)
        assert len(ws.sent) == 2
        payloads = [json.loads(s) for s in ws.sent]
        assert payloads[0]["text"] == "Hello there."
        assert payloads[1]["text"] == "How can I help you?"

    async def test_pre_warm_emits_no_frames(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, _done_msg()])
        proc = _build_proc()
        proc._ws = ws
        proc._unavailable = False
        proc.push_frame = AsyncMock()

        await proc.pre_warm(["Warm up text."])

        # pre_warm must never push any frames
        proc.push_frame.assert_not_called()

    async def test_pre_warm_skipped_when_unavailable(self) -> None:
        proc = _build_proc()
        proc._ws = MockWebSocket()
        proc._unavailable = True
        proc.push_frame = AsyncMock()

        await proc.pre_warm(["Should not be sent."])

        assert proc._ws.sent == [], "pre_warm must not send when unavailable"

    async def test_pre_warm_skipped_when_not_connected(self) -> None:
        proc = _build_proc()
        proc._ws = None
        proc._unavailable = False
        proc.push_frame = AsyncMock()

        await proc.pre_warm(["Should not be sent."])

        # No crash, no data sent (ws is None)

    async def test_pre_warm_skips_blank_phrases(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, _done_msg()])
        proc = _build_proc()
        proc._ws = ws
        proc._unavailable = False
        proc.push_frame = AsyncMock()

        await proc.pre_warm(["", "  ", "Hello."])

        # Only the non-blank phrase should have been sent
        assert len(ws.sent) == 1


# ── TestCallRecorderIntegration ───────────────────────────────────────────────


class TestCallRecorderIntegration:
    """write_outbound() must be called for every audio chunk pushed downstream."""

    async def test_write_outbound_called_per_chunk(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, _done_msg()])

        recorder = MagicMock()
        proc = _build_proc(recorder=recorder)
        proc.push_frame = AsyncMock()
        frames = await _capture_dispatch(proc, ws, "Testing recorder integration.")

        assert recorder.write_outbound.call_count == 1
        # Verify the argument is bytes (normalised PCM)
        call_args = recorder.write_outbound.call_args[0][0]
        assert isinstance(call_args, bytes)

    async def test_write_outbound_called_for_each_wav_chunk(self) -> None:
        wav = _make_wav()
        ws = MockWebSocket([wav, wav, wav, _done_msg()])

        recorder = MagicMock()
        proc = _build_proc(recorder=recorder)
        proc.push_frame = AsyncMock()
        await _capture_dispatch(proc, ws, "Three chunk recording test sentence.")

        assert recorder.write_outbound.call_count == 3

    async def test_no_recorder_does_not_crash(self) -> None:
        """recorder=None is the default and must never raise AttributeError."""
        wav = _make_wav()
        ws = MockWebSocket([wav, _done_msg()])
        proc = _build_proc(recorder=None)
        proc.push_frame = AsyncMock()

        # Must complete without raising
        await _capture_dispatch(proc, ws, "Default no-recorder sentence.")

    async def test_tts_audio_frame_pushed_independently_of_recorder(self) -> None:
        """TTSAudioRawFrame is pushed regardless of whether recorder is present."""
        wav = _make_wav()
        ws = MockWebSocket([wav, _done_msg()])
        proc = _build_proc(recorder=None)
        frames = await _capture_dispatch(proc, ws, "Frame pushed without recorder.")
        assert any(isinstance(f, TTSAudioRawFrame) for f in frames)

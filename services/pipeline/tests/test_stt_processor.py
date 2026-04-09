"""
Unit tests for WhisperSTTProcessor — Day 5 deliverables.

Tests exercise transcription latency, language auto-detection,
latency logging, graceful unavailability fallback, and the
on_transcription callback.

No real Whisper service is required — WebSocket interactions are fully mocked.

Deliverables verified
---------------------
  ✓  5 s audio clip processed in < 400 ms (in-process mock path)
  ✓  English transcript emitted in TranscriptionFrame
  ✓  Hindi  transcript emitted in TranscriptionFrame
  ✓  latency_ms present in whisper_stt.transcription log entry
  ✓  When Whisper is unavailable → buffer cleared, no crash, reconnect scheduled
  ✓  on_transcription(text, language) callback invoked with correct arguments
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# Allow direct imports from services/pipeline/
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection

from processors.stt import WhisperSTTProcessor


# ── Mock WebSocket ─────────────────────────────────────────────────────────────

class MockWebSocket:
    """Lightweight async WS stub that replays pre-queued responses."""

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

    def enqueue(self, response: str | bytes) -> None:
        self._queue.put_nowait(response)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _response(
    text: str,
    language: str = "en",
    elapsed_ms: int = 50,
) -> str:
    """Build a JSON Whisper transcript response."""
    return json.dumps({"text": text, "language": language, "elapsed_ms": elapsed_ms})


def _audio_buffer(seconds: float = 1.0, sample_rate: int = 16_000) -> bytearray:
    """Return a bytearray of silence for the given duration (int16 PCM)."""
    return bytearray(int(sample_rate * seconds) * 2)


async def _run_flush(
    proc: WhisperSTTProcessor,
    ws: MockWebSocket,
) -> list[Any]:
    """Inject *ws* into *proc*, flush, and return all pushed frames."""
    proc._ws = ws
    captured: list[Any] = []

    async def capture(frame: Any, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        captured.append(frame)

    proc.push_frame = capture  # type: ignore[method-assign]
    await proc._flush_and_transcribe()
    return captured


# ── TestTranscriptionLatency ──────────────────────────────────────────────────

class TestTranscriptionLatency:
    """5 s of audio must complete well under the 400 ms SLO in the in-process path."""

    async def test_5s_audio_under_400ms(self) -> None:
        ws = MockWebSocket([_response("hello world")])
        proc = WhisperSTTProcessor()
        proc._audio_buffer = _audio_buffer(5.0)  # 320 000 bytes

        t0 = time.perf_counter()
        frames = await _run_flush(proc, ws)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < 400, (
            f"flush took {elapsed_ms:.1f} ms; expected < 400 ms"
        )
        assert len(frames) == 1
        assert isinstance(frames[0], TranscriptionFrame)
        assert frames[0].text == "hello world"

    async def test_audio_split_into_chunks_plus_end(self) -> None:
        """16 000 bytes → 4 data chunks (4 096 B each) then b'END'."""
        ws = MockWebSocket([_response("ok")])
        proc = WhisperSTTProcessor()
        proc._audio_buffer = _audio_buffer(0.5)  # 16 000 bytes

        await _run_flush(proc, ws)

        data_sent = [m for m in ws.sent if m != b"END"]
        assert ws.sent[-1] == b"END", "END sentinel must be last"
        assert len(data_sent) == 4  # ceil(16 000 / 4 096) = 4

    async def test_empty_buffer_skips_ws(self) -> None:
        """Empty audio buffer must not touch the WebSocket at all."""
        ws = MockWebSocket()
        proc = WhisperSTTProcessor()
        proc._audio_buffer = bytearray()
        proc._ws = ws
        proc.push_frame = AsyncMock()

        await proc._flush_and_transcribe()

        assert ws.sent == []


# ── TestLanguageDetection ─────────────────────────────────────────────────────

class TestLanguageDetection:
    """Whisper-reported language propagates through the processor correctly."""

    async def test_english_transcript_emitted(self) -> None:
        ws = MockWebSocket([_response("Good morning", language="en")])
        proc = WhisperSTTProcessor()
        proc._audio_buffer = _audio_buffer()
        frames = await _run_flush(proc, ws)

        assert len(frames) == 1
        assert isinstance(frames[0], TranscriptionFrame)
        assert frames[0].text == "Good morning"

    async def test_hindi_transcript_emitted(self) -> None:
        ws = MockWebSocket([_response("नमस्ते दुनिया", language="hi")])
        proc = WhisperSTTProcessor()
        proc._audio_buffer = _audio_buffer()
        frames = await _run_flush(proc, ws)

        assert len(frames) == 1
        assert frames[0].text == "नमस्ते दुनिया"

    async def test_no_language_param_in_url_when_auto(self) -> None:
        """When language=None (auto-detect), no ?language= appended to URL."""
        with patch("processors.stt.ws_client.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = OSError("ignored")
            proc = WhisperSTTProcessor(
                whisper_url="ws://host:9000/transcribe/stream",
                language=None,
            )
            await proc._connect()

        used_url: str = mock_conn.call_args[0][0]
        assert "language=" not in used_url

    async def test_language_hint_appended_to_url(self) -> None:
        """language='hi' config must produce …/transcribe/stream?language=hi."""
        with patch("processors.stt.ws_client.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = OSError("ignored")
            proc = WhisperSTTProcessor(
                whisper_url="ws://host:9000/transcribe/stream",
                language="hi",
            )
            await proc._connect()

        used_url: str = mock_conn.call_args[0][0]
        assert "language=hi" in used_url

    async def test_existing_query_param_extended_not_duplicated(self) -> None:
        """Existing query params must get '&language=XX', not '?language=XX'."""
        with patch("processors.stt.ws_client.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = OSError("ignored")
            proc = WhisperSTTProcessor(
                whisper_url="ws://host:9000/transcribe/stream?model=large",
                language="fr",
            )
            await proc._connect()

        used_url: str = mock_conn.call_args[0][0]
        assert "?model=large&language=fr" in used_url


# ── TestLatencyLogging ────────────────────────────────────────────────────────

class TestLatencyLogging:
    """Every successful transcription must emit a structured log with latency_ms."""

    async def test_latency_ms_present_in_log(self) -> None:
        from structlog.testing import capture_logs

        ws = MockWebSocket([_response("test", elapsed_ms=120)])
        proc = WhisperSTTProcessor()
        proc._audio_buffer = _audio_buffer()
        proc.push_frame = AsyncMock()

        with capture_logs() as entries:
            proc._ws = ws
            await proc._flush_and_transcribe()

        hits = [e for e in entries if e.get("event") == "whisper_stt.transcription"]
        assert len(hits) == 1, "One transcription log entry expected"
        assert "latency_ms" in hits[0], (
            f"latency_ms missing from log entry: {hits[0]}"
        )

    async def test_server_elapsed_ms_present_in_log(self) -> None:
        """server_elapsed_ms (from Whisper JSON) must also be logged."""
        from structlog.testing import capture_logs

        ws = MockWebSocket([_response("hi", elapsed_ms=77)])
        proc = WhisperSTTProcessor()
        proc._audio_buffer = _audio_buffer()
        proc.push_frame = AsyncMock()

        with capture_logs() as entries:
            proc._ws = ws
            await proc._flush_and_transcribe()

        entry = next(e for e in entries if e.get("event") == "whisper_stt.transcription")
        assert entry["server_elapsed_ms"] == 77

    async def test_latency_ms_is_non_negative_integer(self) -> None:
        from structlog.testing import capture_logs

        ws = MockWebSocket([_response("hello")])
        proc = WhisperSTTProcessor()
        proc._audio_buffer = _audio_buffer()
        proc.push_frame = AsyncMock()

        with capture_logs() as entries:
            proc._ws = ws
            await proc._flush_and_transcribe()

        entry = next(e for e in entries if e.get("event") == "whisper_stt.transcription")
        assert isinstance(entry["latency_ms"], int)
        assert entry["latency_ms"] >= 0


# ── TestUnavailableFallback ───────────────────────────────────────────────────

class TestUnavailableFallback:
    """When Whisper is reachable, the processor fails gracefully without crashing."""

    async def test_connect_failure_sets_unavailable_flag(self) -> None:
        with patch("processors.stt.ws_client.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = OSError("Connection refused")
            proc = WhisperSTTProcessor()
            await proc._connect()

        assert proc._unavailable is True
        assert proc._ws is None

    async def test_connect_success_clears_unavailable_flag(self) -> None:
        mock_ws = MockWebSocket()
        with patch("processors.stt.ws_client.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            proc = WhisperSTTProcessor()
            proc._unavailable = True  # simulate previous failure
            await proc._connect()

        assert proc._unavailable is False
        assert proc._ws is mock_ws

    async def test_buffer_cleared_when_unavailable(self) -> None:
        proc = WhisperSTTProcessor()
        proc._unavailable = True
        proc._audio_buffer = _audio_buffer(1.0)
        proc.push_frame = AsyncMock()

        with patch("processors.stt.asyncio.create_task"):
            await proc._flush_and_transcribe()

        assert len(proc._audio_buffer) == 0, "Buffer must be drained even on unavailability"

    async def test_no_transcription_frame_when_unavailable(self) -> None:
        proc = WhisperSTTProcessor()
        proc._unavailable = True
        proc._audio_buffer = _audio_buffer()
        pushed: list[Any] = []

        async def capture(frame: Any, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
            pushed.append(frame)

        proc.push_frame = capture  # type: ignore[method-assign]

        with patch("processors.stt.asyncio.create_task"):
            await proc._flush_and_transcribe()

        assert pushed == [], "No frames must be emitted when the service is unavailable"

    async def test_reconnect_task_scheduled_when_unavailable(self) -> None:
        """A background reconnect coroutine must be scheduled on each lost utterance."""
        proc = WhisperSTTProcessor()
        proc._unavailable = True
        proc._audio_buffer = _audio_buffer()
        proc.push_frame = AsyncMock()

        with patch("processors.stt.asyncio.create_task") as mock_ct:
            await proc._flush_and_transcribe()

        mock_ct.assert_called_once()


# ── TestTranscriptionCallback ─────────────────────────────────────────────────

class TestTranscriptionCallback:
    """on_transcription(text, language) is invoked correctly after each transcript."""

    async def test_callback_invoked_with_text_and_language(self) -> None:
        args: list[tuple[str, str | None]] = []

        async def cb(text: str, language: str | None) -> None:
            args.append((text, language))

        ws = MockWebSocket([_response("Namaste", language="hi")])
        proc = WhisperSTTProcessor(on_transcription=cb)
        proc._audio_buffer = _audio_buffer()
        frames = await _run_flush(proc, ws)

        assert len(frames) == 1
        assert args == [("Namaste", "hi")]

    async def test_callback_not_called_on_empty_transcript(self) -> None:
        call_count = 0

        async def cb(text: str, language: str | None) -> None:
            nonlocal call_count
            call_count += 1

        ws = MockWebSocket([json.dumps({"text": "   ", "language": "en"})])
        proc = WhisperSTTProcessor(on_transcription=cb)
        proc._audio_buffer = _audio_buffer()
        proc.push_frame = AsyncMock()
        proc._ws = ws
        await proc._flush_and_transcribe()

        assert call_count == 0, "Callback must not fire for whitespace-only transcripts"

    async def test_no_callback_param_does_not_crash(self) -> None:
        """Omitting on_transcription must not cause AttributeError."""
        ws = MockWebSocket([_response("hello")])
        proc = WhisperSTTProcessor()  # no on_transcription kwarg
        proc._audio_buffer = _audio_buffer()
        frames = await _run_flush(proc, ws)

        assert len(frames) == 1

    async def test_english_and_hindi_sequential_utterances(self) -> None:
        """Two consecutive utterances in different languages both invoke callback."""
        args: list[tuple[str, str | None]] = []

        async def cb(text: str, language: str | None) -> None:
            args.append((text, language))

        proc = WhisperSTTProcessor(on_transcription=cb)
        proc.push_frame = AsyncMock()

        for text, lang in [("Good morning", "en"), ("नमस्ते", "hi")]:
            ws = MockWebSocket([_response(text, language=lang)])
            proc._ws = ws
            proc._audio_buffer = _audio_buffer()
            await proc._flush_and_transcribe()

        assert len(args) == 2
        assert args[0] == ("Good morning", "en")
        assert args[1] == ("नमस्ते", "hi")

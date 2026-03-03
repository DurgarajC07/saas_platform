"""
Unit tests for SileroVADProcessor.

Tests exercise the state machine logic by mocking SileroVADAnalyzer.analyze_audio
to control which VADState is returned for each audio chunk.  The ONNX model is
never loaded during these tests.

Deliverables verified
---------------------
  ✓  3 seconds of silence  → no UserStartedSpeakingFrame emitted
  ✓  1 second of speech    → UserStartedSpeakingFrame emitted
  ✓  Speech then silence   → UserStartedSpeakingFrame + UserStoppedSpeakingFrame
  ✓  Audio forwarded only during speech window
  ✓  All params (vad_threshold, min_speech_ms, silence_ms) propagated to VADParams
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Allow direct imports from services/pipeline/
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.frames.frames import (
    AudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from processors.vad import SileroVADProcessor

# ── helpers ───────────────────────────────────────────────────────────────────

def _silence_frame(ms: int = 20, sample_rate: int = 16_000) -> AudioRawFrame:
    """Create an AudioRawFrame containing ``ms`` milliseconds of silence."""
    n_samples = sample_rate * ms // 1000
    pcm = bytes(n_samples * 2)  # int16 zeros
    return AudioRawFrame(audio=pcm, sample_rate=sample_rate, num_channels=1)


def _speech_frame(ms: int = 20, sample_rate: int = 16_000, freq: float = 200.0) -> AudioRawFrame:
    """Create an AudioRawFrame containing a sine wave at ``freq`` Hz."""
    n_samples  = sample_rate * ms // 1000
    t          = np.linspace(0, ms / 1000, n_samples, endpoint=False)
    sine       = (np.sin(2 * np.pi * freq * t) * 16000).astype(np.int16)
    return AudioRawFrame(audio=sine.tobytes(), sample_rate=sample_rate, num_channels=1)


async def _feed_frames(
    vad: SileroVADProcessor,
    frames: List[AudioRawFrame],
) -> List[object]:
    """
    Feed a sequence of AudioRawFrames through ``vad._handle_audio`` and return
    all frames that were passed to ``push_frame``.
    """
    captured: List[object] = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        captured.append(frame)

    vad.push_frame = capture  # type: ignore[method-assign]

    for frame in frames:
        await vad._handle_audio(frame)

    return captured


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def vad() -> SileroVADProcessor:
    """
    A SileroVADProcessor with the SileroVADAnalyzer constructor mocked so no
    ONNX model is loaded.  The ``analyze_audio`` method is replaced per-test
    via ``patch.object``.
    """
    with patch("processors.vad.SileroVADAnalyzer") as MockAnalyzer:
        instance = MagicMock()
        MockAnalyzer.return_value = instance
        proc = SileroVADProcessor(
            vad_threshold=0.5,
            min_speech_ms=250,
            silence_ms=800,
        )
    return proc


# ── tests ─────────────────────────────────────────────────────────────────────

class TestVADSilence:
    """3 seconds of silence must never trigger speech events."""

    async def test_no_speech_start_on_silence(self, vad: SileroVADProcessor):
        silence_count = 150  # 150 × 20 ms = 3 s

        with patch.object(vad._vad, "analyze_audio", return_value=VADState.QUIET):
            frames  = [_silence_frame() for _ in range(silence_count)]
            emitted = await _feed_frames(vad, frames)

        speech_starts = [f for f in emitted if isinstance(f, UserStartedSpeakingFrame)]
        assert speech_starts == [], (
            f"Expected 0 UserStartedSpeakingFrames for 3 s of silence, "
            f"got {len(speech_starts)}"
        )

    async def test_no_speech_stop_on_silence(self, vad: SileroVADProcessor):
        with patch.object(vad._vad, "analyze_audio", return_value=VADState.QUIET):
            frames  = [_silence_frame() for _ in range(100)]
            emitted = await _feed_frames(vad, frames)

        speech_stops = [f for f in emitted if isinstance(f, UserStoppedSpeakingFrame)]
        assert speech_stops == []

    async def test_audio_not_forwarded_during_silence(self, vad: SileroVADProcessor):
        """AudioRawframes must be dropped (not forwarded) while no speech."""
        with patch.object(vad._vad, "analyze_audio", return_value=VADState.QUIET):
            frames  = [_silence_frame() for _ in range(10)]
            emitted = await _feed_frames(vad, frames)

        audio_forwarded = [f for f in emitted if isinstance(f, AudioRawFrame)]
        assert audio_forwarded == [], "Audio should NOT be forwarded during silence"


class TestVADSpeech:
    """1 second of speech must trigger exactly one speech-start event."""

    async def test_speech_start_emitted(self, vad: SileroVADProcessor):
        speech_count = 50  # 50 × 20 ms = 1 s

        with patch.object(vad._vad, "analyze_audio", return_value=VADState.SPEAKING):
            frames  = [_speech_frame() for _ in range(speech_count)]
            emitted = await _feed_frames(vad, frames)

        speech_starts = [f for f in emitted if isinstance(f, UserStartedSpeakingFrame)]
        assert len(speech_starts) == 1, (
            f"Expected exactly 1 UserStartedSpeakingFrame for 1 s of speech, "
            f"got {len(speech_starts)}"
        )

    async def test_audio_forwarded_during_speech(self, vad: SileroVADProcessor):
        """AudioRawFrames must be forwarded while speech is active."""
        n = 10
        with patch.object(vad._vad, "analyze_audio", return_value=VADState.SPEAKING):
            frames  = [_speech_frame() for _ in range(n)]
            emitted = await _feed_frames(vad, frames)

        audio_forwarded = [f for f in emitted if isinstance(f, AudioRawFrame)]
        # First frame triggers state transition; all frames are forwarded
        assert len(audio_forwarded) == n

    async def test_speech_start_only_once(self, vad: SileroVADProcessor):
        """STARTING state must emit UserStartedSpeakingFrame only on the first transition."""
        with patch.object(vad._vad, "analyze_audio", return_value=VADState.STARTING):
            frames  = [_speech_frame() for _ in range(30)]
            emitted = await _feed_frames(vad, frames)

        speech_starts = [f for f in emitted if isinstance(f, UserStartedSpeakingFrame)]
        assert len(speech_starts) == 1


class TestVADSpeechThenSilence:
    """Full utterance cycle: onset → speech → silence → stop."""

    async def test_full_utterance_cycle(self, vad: SileroVADProcessor):
        captured: list = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            captured.append(frame)

        vad.push_frame = capture  # type: ignore[method-assign]

        # Sequence of VAD states: silence → speech onset → speech → silence
        state_seq = (
            [VADState.QUIET]    * 25 +   # 500 ms silence
            [VADState.STARTING] *  1 +   # onset
            [VADState.SPEAKING] * 50 +   # 1 s speech
            [VADState.STOPPING] *  1 +   # trailing silence detected
            [VADState.QUIET]    * 10     # settled
        )
        state_iter = iter(state_seq)

        with patch.object(vad._vad, "analyze_audio", side_effect=state_iter):
            for _ in range(len(state_seq)):
                await vad._handle_audio(_speech_frame())

        starts = [f for f in captured if isinstance(f, UserStartedSpeakingFrame)]
        stops  = [f for f in captured if isinstance(f, UserStoppedSpeakingFrame)]

        assert len(starts) == 1, f"Expected 1 speech start, got {len(starts)}"
        assert len(stops)  == 1, f"Expected 1 speech stop,  got {len(stops)}"

        # Start must precede stop
        start_idx = next(i for i, f in enumerate(captured) if isinstance(f, UserStartedSpeakingFrame))
        stop_idx  = next(i for i, f in enumerate(captured) if isinstance(f, UserStoppedSpeakingFrame))
        assert start_idx < stop_idx


class TestVADParams:
    """All AgentConfig VAD params must be correctly passed to the analyzer."""

    def test_vad_params_propagated(self):
        with patch("processors.vad.SileroVADAnalyzer") as MockAnalyzer:
            with patch("processors.vad.VADParams") as MockParams:
                SileroVADProcessor(
                    vad_threshold=0.7,
                    min_speech_ms=300,
                    silence_ms=600,
                )
                MockParams.assert_called_once_with(
                    confidence=0.7,
                    start_secs=0.3,
                    stop_secs=0.6,
                )
                MockAnalyzer.assert_called_once()

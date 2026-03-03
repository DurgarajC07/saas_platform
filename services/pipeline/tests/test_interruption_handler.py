"""
Unit tests for InterruptionHandler.

Verifies barge-in detection, TTS frame dropping, and pass-through behaviour.

Deliverables verified
---------------------
  ✓  UserStartedSpeakingFrame → StartInterruptionFrame + TTSStoppedFrame emitted
  ✓  TTSAudioRawFrame dropped while user is speaking
  ✓  UserStoppedSpeakingFrame clears interruption state
  ✓  Enabled=False → transparent pass-through
  ✓  Multiple barge-ins handled cleanly (only one set of cancel frames per onset)
  ✓  barge_in_threshold stored and accessible
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipecat.frames.frames import (
    AudioRawFrame,
    StartInterruptionFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from processors.interrupt import InterruptionHandler

# ── helpers ───────────────────────────────────────────────────────────────────

def _pcm(ms: int = 20, sample_rate: int = 16_000) -> bytes:
    return bytes(sample_rate * ms // 1000 * 2)


def _audio_frame(ms: int = 20) -> AudioRawFrame:
    return AudioRawFrame(audio=_pcm(ms), sample_rate=16_000, num_channels=1)


def _tts_frame() -> TTSAudioRawFrame:
    return TTSAudioRawFrame(audio=_pcm(), sample_rate=24_000, num_channels=1)


async def _send(handler: InterruptionHandler, frames: list) -> List[object]:
    """Feed *frames* into *handler* and return all frames passed to push_frame."""
    captured: List[object] = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        captured.append(frame)

    handler.push_frame = capture  # type: ignore[method-assign]

    for frame in frames:
        await handler.process_frame(frame, FrameDirection.DOWNSTREAM)

    return captured


# ── tests ─────────────────────────────────────────────────────────────────────

class TestBargeIn:
    """Onset of user speech must flush TTS immediately."""

    async def test_interruption_frames_emitted_on_barge_in(self):
        handler  = InterruptionHandler(enabled=True)
        emitted  = await _send(handler, [UserStartedSpeakingFrame()])

        types = [type(f) for f in emitted]
        assert StartInterruptionFrame in types, "StartInterruptionFrame must be emitted"
        assert TTSStoppedFrame        in types, "TTSStoppedFrame must be emitted on barge-in"

    async def test_start_interruption_precedes_tts_stopped(self):
        """StartInterruptionFrame must appear before TTSStoppedFrame."""
        handler = InterruptionHandler(enabled=True)
        emitted = await _send(handler, [UserStartedSpeakingFrame()])

        types = [type(f) for f in emitted]
        start_idx = types.index(StartInterruptionFrame)
        stop_idx  = types.index(TTSStoppedFrame)
        assert start_idx < stop_idx

    async def test_user_started_speaking_forwarded(self):
        """UserStartedSpeakingFrame must still be forwarded downstream."""
        handler = InterruptionHandler(enabled=True)
        emitted = await _send(handler, [UserStartedSpeakingFrame()])

        forwarded = [f for f in emitted if isinstance(f, UserStartedSpeakingFrame)]
        assert len(forwarded) == 1

    async def test_only_one_cancellation_per_utterance(self):
        """Double barge-in must not emit duplicate cancel frames."""
        handler = InterruptionHandler(enabled=True)
        emitted = await _send(handler, [
            UserStartedSpeakingFrame(),
            UserStartedSpeakingFrame(),  # second call while already interrupted
        ])

        starts  = [f for f in emitted if isinstance(f, StartInterruptionFrame)]
        stopped = [f for f in emitted if isinstance(f, TTSStoppedFrame)]
        assert len(starts)  == 1
        assert len(stopped) == 1


class TestTTSDropping:
    """TTS audio must be dropped while user is speaking."""

    async def test_tts_audio_dropped_while_interrupted(self):
        handler = InterruptionHandler(enabled=True)
        # trigger barge-in
        await _send(handler, [UserStartedSpeakingFrame()])

        # while interrupted, TTS frames must be dropped
        captured = await _send(handler, [_tts_frame(), _tts_frame()])

        tts_forwarded = [f for f in captured if isinstance(f, TTSAudioRawFrame)]
        assert tts_forwarded == [], "TTS audio must be dropped when user is speaking"

    async def test_tts_audio_forwarded_after_speech_stops(self):
        """TTS audio must flow normally once the barge-in clears."""
        handler = InterruptionHandler(enabled=True)

        # full cycle: start → stop → new TTS frame
        await _send(handler, [UserStartedSpeakingFrame()])
        await _send(handler, [UserStoppedSpeakingFrame()])
        emitted = await _send(handler, [_tts_frame()])

        tts_forwarded = [f for f in emitted if isinstance(f, TTSAudioRawFrame)]
        assert len(tts_forwarded) == 1, "TTS audio should pass through after speech stops"


class TestSpeechStop:
    """UserStoppedSpeakingFrame must clear the interruption state."""

    async def test_speech_stop_clears_interrupted(self):
        handler = InterruptionHandler(enabled=True)
        await _send(handler, [UserStartedSpeakingFrame()])
        assert handler._interrupted is True

        await _send(handler, [UserStoppedSpeakingFrame()])
        assert handler._interrupted is False

    async def test_speech_stop_forwarded(self):
        handler = InterruptionHandler(enabled=True)
        await _send(handler, [UserStartedSpeakingFrame()])
        emitted = await _send(handler, [UserStoppedSpeakingFrame()])

        forwarded = [f for f in emitted if isinstance(f, UserStoppedSpeakingFrame)]
        assert len(forwarded) == 1


class TestDisabledMode:
    """When enabled=False the processor must be a transparent pass-through."""

    async def test_passthrough_on_user_started_speaking(self):
        handler = InterruptionHandler(enabled=False)
        emitted = await _send(handler, [UserStartedSpeakingFrame()])

        # No cancel frames
        assert not any(isinstance(f, StartInterruptionFrame) for f in emitted)
        assert not any(isinstance(f, TTSStoppedFrame)        for f in emitted)
        # Original frame is forwarded
        assert any(isinstance(f, UserStartedSpeakingFrame)   for f in emitted)

    async def test_tts_not_dropped_when_disabled(self):
        handler = InterruptionHandler(enabled=False)
        emitted = await _send(handler, [
            UserStartedSpeakingFrame(),
            _tts_frame(),
        ])
        tts = [f for f in emitted if isinstance(f, TTSAudioRawFrame)]
        assert len(tts) == 1, "TTS must not be dropped when interruptions disabled"


class TestBargeInThreshold:
    async def test_threshold_stored(self):
        handler = InterruptionHandler(enabled=True, barge_in_threshold=0.4)
        assert handler._barge_in_threshold == pytest.approx(0.4)

    async def test_default_threshold(self):
        handler = InterruptionHandler()
        assert handler._barge_in_threshold == pytest.approx(0.3)

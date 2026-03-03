"""
SileroVADProcessor — AudioRawFrame → speech-segmented frames.

Wraps pipecat's built-in SileroVADAnalyzer (Silero v5, onnxruntime) to segment
a continuous raw-PCM stream into discrete speech utterances.

Frame flow
----------
AudioRawFrame (continuous stream)
    ↓  SileroVADProcessor
UserStartedSpeakingFrame  — emitted once when speech probability crosses threshold
AudioRawFrame             — forwarded only during confirmed speech windows
UserStoppedSpeakingFrame  — emitted once when trailing silence exceeds ``silence_ms``

VAD state machine
-----------------
QUIET → STARTING  : speech onset detected  → emit UserStartedSpeakingFrame
STARTING → SPEAKING : speech confirmed     → keep forwarding audio
SPEAKING → STOPPING : trailing silence     → emit UserStoppedSpeakingFrame
STOPPING → QUIET  : cooldown complete      → ready for next utterance

Parameters (all read from AgentConfig)
---------------------------------------
vad_threshold   : float  speech probability threshold (0.1–0.95, default 0.5)
min_speech_ms   : int    minimum speech duration to confirm onset (default 250 ms)
silence_ms      : int    trailing silence to confirm end of utterance (default 800 ms)
sample_rate     : int    expected PCM sample rate (default 16 000 Hz)
"""

from __future__ import annotations

from typing import Any

import structlog
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.frames.frames import (
    AudioRawFrame,
    EndFrame,
    Frame,
    StartFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class SileroVADProcessor(FrameProcessor):
    """
    Voice Activity Detection using the Silero v5 ONNX model.

    Emits ``UserStartedSpeakingFrame`` / ``UserStoppedSpeakingFrame`` events
    and forwards ``AudioRawFrame`` only during confirmed speech windows.
    All parameters are read from ``AgentConfig`` so behaviour is tunable
    per-agent without code changes.

    Parameters
    ----------
    vad_threshold :
        Speech probability score (0.0–1.0) above which audio is considered
        speech.  Lower values capture quieter or accented voices but raise
        false-positive rate.  Default ``0.5``.
    min_speech_ms :
        Minimum consecutive milliseconds of detected speech before emitting
        ``UserStartedSpeakingFrame``.  Filters out click-sounds and typing.
        Default ``250`` ms.
    silence_ms :
        Silence duration (ms) after speech before ``UserStoppedSpeakingFrame``
        is emitted.  Longer values tolerate mid-sentence pauses; shorter values
        improve turn-taking latency.  Default ``800`` ms.
    sample_rate :
        PCM sample rate expected by the model.  Silero v5 requires 16 000 Hz.
    """

    def __init__(
        self,
        vad_threshold: float   = 0.5,
        min_speech_ms: int     = 250,
        silence_ms: int        = 800,
        sample_rate: int       = 16_000,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._sample_rate = sample_rate
        self._speaking    = False
        self._log = logger.bind(processor="SileroVAD")

        self._vad = SileroVADAnalyzer(
            sample_rate=sample_rate,
            params=VADParams(
                confidence=vad_threshold,
                start_secs=min_speech_ms / 1000.0,
                stop_secs=silence_ms   / 1000.0,
            ),
        )

    # ── Frame processing ─────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, AudioRawFrame):
            await self._handle_audio(frame)
        else:
            await self.push_frame(frame, direction)

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _handle_audio(self, frame: AudioRawFrame) -> None:
        new_state: VADState = self._vad.analyze_audio(frame.audio)

        # ---------- speech onset ----------
        if new_state in (VADState.STARTING, VADState.SPEAKING) and not self._speaking:
            self._speaking = True
            self._log.debug("vad.speech_started")
            await self.push_frame(UserStartedSpeakingFrame())

        # ---------- speech end ----------
        elif new_state in (VADState.STOPPING, VADState.QUIET) and self._speaking:
            self._speaking = False
            self._log.debug("vad.speech_stopped")
            await self.push_frame(UserStoppedSpeakingFrame())

        # Forward audio downstream only while speech is confirmed
        if self._speaking:
            await self.push_frame(frame)

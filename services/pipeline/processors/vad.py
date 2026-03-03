"""
SileroVADProcessor — AudioRawFrame → speech-segmented AudioRawFrame.

Wraps pipecat's built-in SileroVADAnalyzer (which uses onnxruntime to run the
Silero v5 ONNX model) to segment a continuous audio stream into discrete
speech utterances.

Frame flow
----------
AudioRawFrame (continuous)
    ↓  SileroVADProcessor
UserStartedSpeakingFrame  — emitted when speech probability crosses threshold
AudioRawFrame             — forwarded only during active speech
UserStoppedSpeakingFrame  — emitted when silence exceeds `silence_ms`

WhisperSTTProcessor listens for UserStoppedSpeakingFrame to trigger flush.

Parameters
----------
threshold        : float  speech probability threshold (default 0.5)
min_speech_ms    : int    minimum duration to classify as speech (default 250ms)
silence_ms       : int    trailing silence before UserStoppedSpeakingFrame (default 800ms)
sample_rate      : int    audio sample rate expected by Silero (16000)
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

    Emits ``UserStartedSpeakingFrame`` and ``UserStoppedSpeakingFrame``
    events; forwards ``AudioRawFrame`` only during confirmed speech.
    """

    def __init__(
        self,
        threshold: float     = 0.5,
        min_speech_ms: int   = 250,
        silence_ms: int      = 800,
        sample_rate: int     = 16000,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._sample_rate = sample_rate
        self._speaking    = False
        self._log = logger.bind(processor="SileroVAD")

        # Pipecat's built-in Silero wrapper
        self._vad = SileroVADAnalyzer(
            params=VADParams(
                confidence=threshold,
                start_secs=min_speech_ms / 1000.0,
                stop_secs=silence_ms / 1000.0,
            )
        )

    # ── Frame processing ─────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, AudioRawFrame):
            await self._handle_audio(frame)

        elif isinstance(frame, (StartFrame, EndFrame)):
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _handle_audio(self, frame: AudioRawFrame) -> None:
        new_state: VADState = self._vad.analyze_audio(frame.audio)

        if new_state == VADState.STARTING and not self._speaking:
            self._speaking = True
            self._log.debug("vad.speech_started")
            await self.push_frame(UserStartedSpeakingFrame())

        elif new_state == VADState.STOPPING and self._speaking:
            self._speaking = False
            self._log.debug("vad.speech_stopped")
            await self.push_frame(UserStoppedSpeakingFrame())

        # Forward audio frame downstream only while speech is active
        if self._speaking:
            await self.push_frame(frame)

"""
InterruptionHandler — detect user barge-in and flush the TTS pipeline.

When the user starts speaking during TTS playback (the "barge-in" case), this
processor:
  1. Emits a StartInterruptionFrame — KokoroTTSProcessor cancels pending synthesis
  2. Emits a StopInterruptionFrame once the user stops speaking
  3. Drains any TTSAudioRawFrames that are still in-flight so the speaker
     goes silent immediately

Enabled via ``agent_config.allow_interruptions = True`` (default).

Frame flow
----------
UserStartedSpeakingFrame (from VAD)
    → StartInterruptionFrame  (downstream flush signal)
    → drop any buffered TTSAudioRawFrame until UserStoppedSpeakingFrame

UserStoppedSpeakingFrame
    → StopInterruptionFrame
"""

from __future__ import annotations

from typing import Any

import structlog
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    StartFrame,
    StartInterruptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class InterruptionHandler(FrameProcessor):
    """
    Barge-in detection and TTS pipeline flushing.

    Parameters
    ----------
    enabled : bool
        When ``False`` this processor is a transparent pass-through — useful
        for speaker-only or non-interruptible agent types.
    """

    def __init__(self, enabled: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._enabled    = enabled
        self._interrupted = False
        self._log = logger.bind(processor="InterruptionHandler")

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if not self._enabled:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStartedSpeakingFrame):
            if not self._interrupted:
                self._interrupted = True
                self._log.info("interruption.barge_in_detected")
                await self.push_frame(StartInterruptionFrame())
            await self.push_frame(frame, direction)

        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._interrupted:
                self._interrupted = False
                self._log.debug("interruption.barge_in_cleared")
            await self.push_frame(frame, direction)

        elif isinstance(frame, TTSAudioRawFrame) and self._interrupted:
            # Drop TTS audio while user is speaking — creates immediate silence
            self._log.debug("interruption.dropping_tts_audio")

        elif isinstance(frame, (StartFrame, EndFrame)):
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

"""
InterruptionHandler — detect user barge-in and flush the TTS pipeline.

When the user starts speaking during TTS playback (the "barge-in" case), this
processor must immediately:

  1. Emit ``StartInterruptionFrame``   — pipecat's built-in scheduler drains
                                         the downstream processor queues
  2. Emit ``TTSStoppedFrame``          — signals KokoroTTSProcessor to abort
                                         current synthesis and discard buffers
  3. Drop any ``TTSAudioRawFrame`` that arrive while the user is speaking to
     ensure the speaker goes silent without a crackling tail

When the user stops speaking ``UserStoppedSpeakingFrame`` is forwarded so the
STT / LLM chain can process the captured utterance.

This processor is a transparent pass-through when ``enabled=False`` (set
for ``speaker_only`` agents or when ``allow_interruptions=False`` in
AgentConfig).

Frame flow
----------
UserStartedSpeakingFrame
    → StartInterruptionFrame        (flush downstream queues)
    → TTSStoppedFrame               (stop TTS synthesis)
    → UserStartedSpeakingFrame      (forwarded for STT)
    [TTSAudioRawFrame dropped while _interrupted]

UserStoppedSpeakingFrame
    → UserStoppedSpeakingFrame      (forwarded; triggers STT flush)
    [interruption flag cleared]

Parameters (read from AgentConfig)
-----------------------------------
enabled          : mirrors ``allow_interruptions``
barge_in_threshold : minimum VAD confidence to accept as a real barge-in.
                     Future hook — Silero already gates on its own threshold;
                     this allows an additional agent-level filter (0.0–1.0).
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
    TTSStoppedFrame,
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
    enabled :
        When ``False`` this processor is a transparent pass-through.
        Set to ``False`` for speaker-only or non-interruptible agents.
    barge_in_threshold :
        Minimum speech confidence (0.0–1.0) required to treat an incoming
        ``UserStartedSpeakingFrame`` as a true barge-in.  Currently reserved
        for future per-frame energy gating.  Default ``0.3``.
    """

    def __init__(
        self,
        enabled: bool            = True,
        barge_in_threshold: float = 0.3,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._enabled           = enabled
        self._barge_in_threshold = barge_in_threshold
        self._interrupted        = False
        self._tts_frames_dropped = 0
        self._log = logger.bind(processor="InterruptionHandler")

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if not self._enabled:
            await self.push_frame(frame, direction)
            return

        # ── Barge-in onset ───────────────────────────────────────────────────
        if isinstance(frame, UserStartedSpeakingFrame):
            if not self._interrupted:
                self._interrupted        = True
                self._tts_frames_dropped = 0
                self._log.info(
                    "interruption.barge_in_detected",
                    threshold=self._barge_in_threshold,
                )
                # 1. Signal pipecat to drain downstream processor queues
                await self.push_frame(StartInterruptionFrame())
                # 2. Tell TTS processor to abort current synthesis immediately
                await self.push_frame(TTSStoppedFrame())
            await self.push_frame(frame, direction)

        # ── Barge-in end ─────────────────────────────────────────────────────
        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._interrupted:
                self._log.debug(
                    "interruption.barge_in_cleared",
                    tts_frames_dropped=self._tts_frames_dropped,
                )
                self._interrupted = False
            await self.push_frame(frame, direction)

        # ── Drop stale TTS audio while user is speaking ──────────────────────
        elif isinstance(frame, TTSAudioRawFrame) and self._interrupted:
            self._tts_frames_dropped += 1
            self._log.debug(
                "interruption.dropping_tts_audio",
                n=self._tts_frames_dropped,
            )
            # intentionally NOT forwarding this frame

        elif isinstance(frame, (StartFrame, EndFrame)):
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

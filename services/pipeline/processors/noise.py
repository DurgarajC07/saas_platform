"""
DeepFilterNetProcessor — AudioRawFrame → denoised AudioRawFrame.

Runs DeepFilterNet3 (32 kHz wideband RNN noise suppressor) on each incoming
audio frame before passing it to VAD and STT.  Improves transcription accuracy
in noisy environments (background speech, keyboard, traffic).

Enabled only when ``agent_config.noise_removal_enabled = True``.

Implementation note
-------------------
DeepFilterNet is synchronous and CPU-bound.  Audio is run through it in a
thread pool executor to avoid blocking the asyncio event loop.  The model is
loaded once at startup and kept in memory for the lifetime of the session.

Dependency: ``pip install deepfilternet``  (added to pipeline requirements.txt)
The pipeline Dockerfile installs it automatically.

If the package is unavailable (e.g. running outside Docker), the processor
fails open: audio frames are forwarded unchanged with a one-time warning.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from pipecat.frames.frames import AudioRawFrame, EndFrame, Frame, StartFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class DeepFilterNetProcessor(FrameProcessor):
    """
    Background noise suppression using DeepFilterNet3.

    All audio is resampled to 32 kHz for DeepFilterNet, then downsampled back
    to 16 kHz before forwarding to the next processor.

    Parameters
    ----------
    attenuation_limit_db : float
        Maximum noise attenuation in dB (default 100.0 — no limit).
    """

    def __init__(
        self,
        attenuation_limit_db: float = 100.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._attenuation_db = attenuation_limit_db
        self._model: Any      = None
        self._df_state: Any   = None
        self._available: bool = False
        self._warned: bool    = False
        self._log = logger.bind(processor="DeepFilterNet")

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self._load_model()
            await self.push_frame(frame, direction)

        elif isinstance(frame, AudioRawFrame):
            if self._available:
                denoised = await asyncio.get_event_loop().run_in_executor(
                    None, self._denoise, frame.audio
                )
                await self.push_frame(
                    AudioRawFrame(audio=denoised, sample_rate=16000, num_channels=1)
                )
            else:
                # Fail open — forward audio unchanged
                if not self._warned:
                    self._log.warning("deepfilternet.unavailable — forwarding raw audio")
                    self._warned = True
                await self.push_frame(frame, direction)

        elif isinstance(frame, EndFrame):
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── Internal ────────────────────────────────────────────────────────────

    async def _load_model(self) -> None:
        try:
            from df import enhance, init_df  # type: ignore[import]

            loop = asyncio.get_event_loop()
            model, df_state, _ = await loop.run_in_executor(
                None,
                lambda: init_df(
                    config_allow_defaults=True,
                    log_level="none",
                ),
            )
            self._model    = model
            self._df_state = df_state
            self._available = True
            self._log.info("deepfilternet.loaded")
        except ImportError:
            self._log.warning(
                "deepfilternet.not_installed — add 'deepfilternet' to requirements.txt"
            )
        except Exception as exc:
            self._log.error("deepfilternet.load_failed", error=str(exc))

    def _denoise(self, pcm_bytes: bytes) -> bytes:
        """
        Run DeepFilterNet on raw int16 PCM bytes (16 kHz mono).
        Returns denoised int16 PCM bytes at 16 kHz.
        """
        import numpy as np
        from df import enhance  # type: ignore[import]

        # int16 → float32 normalised
        audio = (
            np.frombuffer(pcm_bytes, dtype=np.int16)
            .astype(np.float32)
            / 32768.0
        )

        # DeepFilterNet expects shape (channels, samples) at 32 kHz
        # Upsample 16k → 32k (simple repeat — good enough for noise removal)
        audio_32k = np.repeat(audio, 2)[np.newaxis, :]

        enhanced_32k = enhance(self._model, self._df_state, audio_32k)

        # Downsample 32k → 16k (take every other sample)
        enhanced_16k = enhanced_32k[0, ::2]

        # float32 → int16
        return (np.clip(enhanced_16k, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

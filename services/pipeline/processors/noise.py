"""
Two-stage noise removal processors.

Stage 1 — RNNoiseProcessor      (< 1 ms/frame, always-on when level >= rnnoise)
Stage 2 — DeepFilterNetProcessor  (~5 ms/frame, enabled when level = deepfilternet)

Ordering in the pipeline:  input → [RNNoise] → [DeepFilterNet] → VAD → STT …

Both processors fail-open: if the underlying library is unavailable (e.g.
the package was not installed or the native extension failed to build), audio
is forwarded unchanged with a single warning log entry.

RNNoise
-------
Recurrent neural network noise suppressor originally developed by Mozilla/Xiph.
Works on 10 ms frames of 48 kHz PCM16 mono (480 samples = 960 bytes).
Our audio arrives at 16 kHz, so each 20 ms pipecat chunk (320 samples) is:
  • upsampled 3× → 960 samples @ 48 kHz  (linear interpolation, numpy)
  • split into two 480-sample RNNoise frames
  • downsampled 3× → 320 samples @ 16 kHz and forwarded
Total CPU overhead: < 1 ms on any modern core.

DeepFilterNet
-------------
Deep learning wideband speech enhancer (DFNet-Conformer, latency ≈ 5 ms).
Accepts float32 audio, processes at 48 kHz, returns float32 at 48 kHz.
We up/downsample the same way as for RNNoise but keep the full bandwidth.
Model is loaded once per session in a thread-pool executor to avoid blocking
the asyncio event loop.

Dependency install (already in requirements.txt):
  pip install rnnoise deepfilternet
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import structlog
from pipecat.frames.frames import AudioRawFrame, EndFrame, Frame, StartFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_IN_RATE   = 16_000   # pipeline sample rate
_RNN_RATE  = 48_000   # RNNoise required rate
_UPSAMPLE  = _RNN_RATE // _IN_RATE   # 3
_RNN_FRAME = 480      # samples per RNNoise frame at 48 kHz (= 10 ms)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — RNNoise
# ─────────────────────────────────────────────────────────────────────────────

class RNNoiseProcessor(FrameProcessor):
    """
    Stage 1 noise removal using the RNNoise RNN denoiser.

    Processes raw int16 PCM at 16 kHz by:
      1. Upsampling 3× to 48 kHz (linear interpolation).
      2. Feeding 10 ms chunks (480 samples) to ``rnnoise.RNNoise``.
      3. Downsampling 3× back to 16 kHz.

    Leftover samples between chunks are buffered internally so no audio
    is dropped regardless of incoming chunk size.

    Fails open: if ``rnnoise`` is not installed the processor is a no-op.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._rnn: Any         = None
        self._available: bool  = False
        self._warned: bool     = False
        # Samples buffered at 48 kHz waiting for a full 480-sample RNNoise frame
        self._buf48: np.ndarray = np.empty(0, dtype=np.float32)
        self._log = logger.bind(processor="RNNoise")

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._init_rnnoise()
            await self.push_frame(frame, direction)

        elif isinstance(frame, AudioRawFrame):
            if self._available:
                denoised = self._process(frame.audio)
                await self.push_frame(
                    AudioRawFrame(audio=denoised, sample_rate=_IN_RATE, num_channels=1)
                )
            else:
                if not self._warned:
                    self._log.warning("rnnoise.unavailable — forwarding raw audio")
                    self._warned = True
                await self.push_frame(frame, direction)

        elif isinstance(frame, EndFrame):
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── internal ─────────────────────────────────────────────────────────────

    def _init_rnnoise(self) -> None:
        try:
            from rnnoise import RNNoise  # type: ignore[import]
            self._rnn       = RNNoise()
            self._available = True
            self._log.info("rnnoise.loaded")
        except ImportError:
            self._log.warning(
                "rnnoise.not_installed — add 'rnnoise' to requirements.txt"
            )
        except Exception as exc:
            self._log.error("rnnoise.init_failed", error=str(exc))

    def _process(self, pcm_bytes: bytes) -> bytes:
        """
        Denoise one pipecat audio chunk (arbitrary size, 16 kHz int16).

        Returns denoised int16 PCM at 16 kHz.
        """
        # int16 → float32  [-1, 1]
        samples16k = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Upsample 16 → 48 kHz via linear interpolation
        x_old = np.arange(len(samples16k))
        x_new = np.linspace(0, len(samples16k) - 1, len(samples16k) * _UPSAMPLE)
        samples48k = np.interp(x_new, x_old, samples16k).astype(np.float32)

        # Append to residual buffer
        self._buf48 = np.concatenate([self._buf48, samples48k])

        # Process complete 480-sample frames
        out48: list[np.ndarray] = []
        while len(self._buf48) >= _RNN_FRAME:
            chunk      = self._buf48[:_RNN_FRAME]
            self._buf48 = self._buf48[_RNN_FRAME:]
            # rnnoise expects int16 bytes (480 samples × 2 bytes = 960 bytes)
            chunk_i16 = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
            denoised_bytes, _vad_prob = self._rnn.process_frame(chunk_i16.tobytes())
            out48.append(
                np.frombuffer(denoised_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            )

        if not out48:
            # Not enough samples yet — return the original (no buffering artefacts)
            return pcm_bytes

        denoised48k = np.concatenate(out48)

        # Downsample 48 → 16 kHz (take every 3rd sample)
        denoised16k = denoised48k[::_UPSAMPLE]

        return (np.clip(denoised16k, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — DeepFilterNet
# ─────────────────────────────────────────────────────────────────────────────

class DeepFilterNetProcessor(FrameProcessor):
    """
    Stage 2 noise removal using DeepFilterNet3.

    Runs synchronous (CPU-bound) inference in a thread-pool executor so the
    asyncio event loop is not blocked.  Model is loaded once at ``StartFrame``.

    Parameters
    ----------
    attenuation_limit_db :
        Maximum noise attenuation in dB (default 100 dB — no cap).

    Fails open: if ``deepfilternet`` is not installed, audio is forwarded
    unchanged with a one-time warning.
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

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self._load_model()
            await self.push_frame(frame, direction)

        elif isinstance(frame, AudioRawFrame):
            if self._available:
                loop = asyncio.get_event_loop()
                denoised = await loop.run_in_executor(None, self._denoise, frame.audio)
                await self.push_frame(
                    AudioRawFrame(audio=denoised, sample_rate=_IN_RATE, num_channels=1)
                )
            else:
                if not self._warned:
                    self._log.warning("deepfilternet.unavailable — forwarding raw audio")
                    self._warned = True
                await self.push_frame(frame, direction)

        elif isinstance(frame, EndFrame):
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── internal ────────────────────────────────────────────────────────────

    async def _load_model(self) -> None:
        try:
            from df import init_df  # type: ignore[import]

            loop = asyncio.get_event_loop()
            model, df_state, _ = await loop.run_in_executor(
                None,
                lambda: init_df(config_allow_defaults=True, log_level="none"),
            )
            self._model     = model
            self._df_state  = df_state
            self._available = True
            self._log.info("deepfilternet.loaded")
        except ImportError:
            self._log.warning(
                "deepfilternet.not_installed — add 'deepfilternet' to requirements.txt"
            )
        except Exception as exc:
            self._log.error("deepfilternet.load_failed", error=str(exc))

    def _denoise(self, pcm_bytes: bytes) -> bytes:
        """Run DeepFilterNet on int16 PCM at 16 kHz; return int16 PCM at 16 kHz."""
        from df import enhance  # type: ignore[import]

        # int16 → float32  [-1, 1]
        audio16k = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Upsample 16 → 48 kHz for DeepFilterNet (shape: channels × samples)
        x_old   = np.arange(len(audio16k))
        x_new   = np.linspace(0, len(audio16k) - 1, len(audio16k) * _UPSAMPLE)
        audio48k = np.interp(x_new, x_old, audio16k)[np.newaxis, :].astype(np.float32)

        enhanced48k = enhance(self._model, self._df_state, audio48k)

        # Downsample 48 → 16 kHz
        enhanced16k = enhanced48k[0, ::_UPSAMPLE]

        return (np.clip(enhanced16k, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

"""
Pipeline service metrics — per-stage latency tracking + GPU utilization.

Provides a process-wide ``PipelineMetrics`` singleton that processors write
to during normal operation.  The ``GET /metrics`` HTTP endpoint reads a
``MetricsSnapshot`` from it.

Rolling window
--------------
The last ``_WINDOW`` (50) samples are kept for each stage.  Averages and p95
are calculated over that window so the numbers reflect recent performance
rather than all-time figures.

GPU utilization
---------------
Attempted via ``pynvml`` (zero-subprocess cost once initialised).  Falls back
to ``subprocess nvidia-smi``.  Returns ``None`` when neither is available
(e.g. CPU-only deployment or container without GPU passthrough).
"""

from __future__ import annotations

import collections
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Deque

import structlog

log = structlog.get_logger(__name__)

# Rolling-average window size
_WINDOW: int = 50


# ── GPU probing ───────────────────────────────────────────────────────────────


def _gpu_utilization() -> int | None:
    """
    Return GPU core utilization (0–100 %) for device 0, or ``None``.

    Tries pynvml first (negligible overhead once NVML is initialised),
    then falls back to ``nvidia-smi``, and silently returns ``None`` if
    the GPU or tooling is unavailable.
    """
    try:
        import pynvml  # type: ignore[import]

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        return int(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu)
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            timeout=1,
        )
        return int(out.decode().strip())
    except Exception:
        return None


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass
class MetricsSnapshot:
    """Point-in-time view of the pipeline service latency and capacity."""

    # Capacity
    sessions_active: int
    max_concurrent_calls: int

    # Stage averages (ms, None = no samples yet)
    avg_vad_ms: float | None
    avg_stt_ms: float | None
    avg_llm_ttft_ms: float | None
    avg_tts_ttfb_ms: float | None
    avg_e2e_ms: float | None

    # p95 end-to-end latency
    p95_e2e_ms: float | None

    # GPU
    gpu_utilization_pct: int | None

    # Service counters
    total_calls_served: int
    uptime_s: float

    def to_dict(self) -> dict:
        return asdict(self)


# ── Accumulator ───────────────────────────────────────────────────────────────


class PipelineMetrics:
    """
    Rolling-window latency accumulator.

    All ``record_*`` methods are safe to call from any async task in a
    single-process deployment (GIL protects deque appends).
    """

    def __init__(self, max_concurrent_calls: int = 3) -> None:
        self._max_concurrent    = max_concurrent_calls
        self._started_at        = time.monotonic()
        self._total_calls       = 0
        self._active_sessions   = 0

        self._vad:  Deque[float] = collections.deque(maxlen=_WINDOW)
        self._stt:  Deque[float] = collections.deque(maxlen=_WINDOW)
        self._llm:  Deque[float] = collections.deque(maxlen=_WINDOW)
        self._tts:  Deque[float] = collections.deque(maxlen=_WINDOW)
        self._e2e:  Deque[float] = collections.deque(maxlen=_WINDOW)

    # ── Write ─────────────────────────────────────────────────────────────────

    def record_vad_ms(self, ms: float) -> None:
        """Record VAD speech-onset detection latency."""
        self._vad.append(ms)

    def record_stt_ms(self, ms: float) -> None:
        """Record STT round-trip latency (audio send → transcript received)."""
        self._stt.append(ms)

    def record_llm_ttft_ms(self, ms: float) -> None:
        """Record LLM time-to-first-token."""
        self._llm.append(ms)

    def record_tts_ttfb_ms(self, ms: float) -> None:
        """Record TTS time-to-first-audio (dispatch send → first WAV chunk)."""
        self._tts.append(ms)

    def record_e2e_ms(self, ms: float) -> None:
        """Record full end-to-end latency for one completed call."""
        self._e2e.append(ms)
        self._total_calls += 1

    def set_active_sessions(self, count: int) -> None:
        """Update the live session count (called by SessionManager)."""
        self._active_sessions = count

    # ── Read ──────────────────────────────────────────────────────────────────

    def snapshot(self) -> MetricsSnapshot:
        """Return a point-in-time snapshot of all metrics."""

        def _avg(d: Deque[float]) -> float | None:
            return round(sum(d) / len(d), 1) if d else None

        def _p95(d: Deque[float]) -> float | None:
            if not d:
                return None
            s = sorted(d)
            idx = max(0, int(len(s) * 0.95) - 1)
            return round(s[idx], 1)

        return MetricsSnapshot(
            sessions_active     = self._active_sessions,
            max_concurrent_calls= self._max_concurrent,
            avg_vad_ms          = _avg(self._vad),
            avg_stt_ms          = _avg(self._stt),
            avg_llm_ttft_ms     = _avg(self._llm),
            avg_tts_ttfb_ms     = _avg(self._tts),
            avg_e2e_ms          = _avg(self._e2e),
            p95_e2e_ms          = _p95(self._e2e),
            gpu_utilization_pct = _gpu_utilization(),
            total_calls_served  = self._total_calls,
            uptime_s            = round(time.monotonic() - self._started_at, 1),
        )


# ── Process-wide singleton ────────────────────────────────────────────────────

_metrics: PipelineMetrics | None = None


def init_metrics(max_concurrent_calls: int = 3) -> PipelineMetrics:
    """
    Initialise the process-wide singleton.

    Must be called once at application startup before any processors run.
    Returns the new instance so the caller can store a reference if needed.
    """
    global _metrics
    _metrics = PipelineMetrics(max_concurrent_calls=max_concurrent_calls)
    log.info("pipeline_metrics_initialized", max_concurrent_calls=max_concurrent_calls)
    return _metrics


def get_metrics() -> PipelineMetrics | None:
    """
    Return the process-wide singleton, or ``None`` if not yet initialised.

    Processors call this with a null-check so they degrade gracefully when
    run inside unit tests that never call ``init_metrics()``.
    """
    return _metrics

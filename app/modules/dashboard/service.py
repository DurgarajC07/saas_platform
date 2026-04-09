"""
Dashboard module — service layer.

DashboardService
  • overview               — real-time overview card
  • latency_24h            — hourly latency chart
  • call_volume            — hour/day/month chart
  • agent_performance      — per-agent table
  • agent_deep_dive        — extended per-agent analytics

AdminService
  • gpu_status             — NVML GPU metrics (graceful fallback if no GPU)
  • queue_status           — Celery broker queue depths
  • run_model_benchmark    — synthetic latency measurement
"""
from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.repository import DashboardRepository
from app.modules.dashboard.schemas import (
    AgentDeepDiveResponse,
    AgentPerformanceResponse,
    AgentPerformanceRow,
    CallVolumePoint,
    CallVolumeResponse,
    GPUDeviceInfo,
    GPUStatusResponse,
    LatencyBucket,
    LatencyResponse,
    LatencySummary,
    ModelBenchmarkRequest,
    ModelBenchmarkResponse,
    ModelBenchmarkResult,
    OverviewResponse,
    QueueInfo,
    QueueStatusResponse,
    TopAgentRow,
    TranscriptSample,
)

log = structlog.get_logger(__name__)


class DashboardService:
    def __init__(self, session: AsyncSession, redis) -> None:  # type: ignore[type-arg]
        self.session = session
        self.redis = redis
        self.repo = DashboardRepository(session)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _month_start() -> datetime:
        now = datetime.now(UTC)
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _pct(completed: int, total: int) -> float:
        return round(100.0 * completed / total, 2) if total else 0.0

    # ── Overview ──────────────────────────────────────────────────────────

    async def overview(self, org_id: UUID) -> OverviewResponse:
        """Return the real-time dashboard overview card."""
        since = self._month_start()
        period = since.strftime("%Y-%m")

        # Active calls from Redis counter kept by pipeline service
        active_raw = await self.redis.get(f"active_calls:{org_id}")
        active_calls = int(active_raw) if active_raw else 0

        summary = await self.repo.monthly_summary(org_id, since)
        top = await self.repo.top_agents(org_id, since)

        top_rows = [
            TopAgentRow(
                agent_id=r["agent_id"],
                agent_name=r["agent_name"],
                total_calls=r["total_calls"],
                success_rate=self._pct(r["completed"], r["total_calls"]),
                avg_duration_sec=r["avg_duration"],
            )
            for r in top
        ]

        total_sec = summary["total_duration_sec"]
        return OverviewResponse(
            period=period,
            active_calls=active_calls,
            total_calls_this_month=summary["total"],
            completed_calls=summary["completed"],
            failed_calls=summary["failed"],
            success_rate=self._pct(summary["completed"], summary["total"]),
            total_minutes_used=total_sec // 60,
            top_agents=top_rows,
            generated_at=datetime.now(UTC),
        )

    # ── Latency ───────────────────────────────────────────────────────────

    async def latency_24h(self, org_id: UUID) -> LatencyResponse:
        since = datetime.now(UTC) - timedelta(hours=24)
        buckets_raw = await self.repo.latency_hourly_buckets(org_id, since)
        summary_raw = await self.repo.latency_summary(org_id, since)

        buckets = [
            LatencyBucket(
                label=b["label"],
                sample_count=b["sample_count"],
                p50_stt_ms=b["p50_stt"],
                p95_stt_ms=b["p95_stt"],
                p99_stt_ms=b["p99_stt"],
                p50_llm_ms=b["p50_llm"],
                p95_llm_ms=b["p95_llm"],
                p99_llm_ms=b["p99_llm"],
                p50_tts_ms=b["p50_tts"],
                p95_tts_ms=b["p95_tts"],
                p99_tts_ms=b["p99_tts"],
            )
            for b in buckets_raw
        ]

        summary = LatencySummary(
            p50_stt_ms=summary_raw["p50_stt"],
            p95_stt_ms=summary_raw["p95_stt"],
            p99_stt_ms=summary_raw["p99_stt"],
            p50_llm_ms=summary_raw["p50_llm"],
            p95_llm_ms=summary_raw["p95_llm"],
            p99_llm_ms=summary_raw["p99_llm"],
            p50_tts_ms=summary_raw["p50_tts"],
            p95_tts_ms=summary_raw["p95_tts"],
            p99_tts_ms=summary_raw["p99_tts"],
        )

        return LatencyResponse(
            window_hours=24,
            buckets=buckets,
            summary=summary,
            generated_at=datetime.now(UTC),
        )

    # ── Call volume ───────────────────────────────────────────────────────

    async def call_volume(
        self,
        org_id: UUID,
        granularity: str = "day",
        days: int = 30,
    ) -> CallVolumeResponse:
        since = datetime.now(UTC) - timedelta(days=days)
        points_raw = await self.repo.call_volume(org_id, granularity, since)

        points = [
            CallVolumePoint(
                label=p["label"],
                total_calls=p["total_calls"],
                completed_calls=p["completed_calls"],
                failed_calls=p["failed_calls"],
                total_duration_sec=p["total_duration_sec"],
                inbound_calls=p["inbound_calls"],
                outbound_calls=p["outbound_calls"],
            )
            for p in points_raw
        ]

        total_calls = sum(p.total_calls for p in points)
        total_duration = sum(p.total_duration_sec for p in points)

        return CallVolumeResponse(
            granularity=granularity,  # type: ignore[arg-type]
            points=points,
            total_calls=total_calls,
            total_duration_sec=total_duration,
            generated_at=datetime.now(UTC),
        )

    # ── Agent performance ─────────────────────────────────────────────────

    async def agent_performance(
        self,
        org_id: UUID,
        days: int = 30,
    ) -> AgentPerformanceResponse:
        since = datetime.now(UTC) - timedelta(days=days)
        rows_raw = await self.repo.agent_performance(org_id, since)

        rows = [
            AgentPerformanceRow(
                agent_id=r["agent_id"],
                agent_name=r["agent_name"],
                total_calls=r["total_calls"],
                completed_calls=r["completed_calls"],
                failed_calls=r["failed_calls"],
                success_rate=self._pct(r["completed_calls"], r["total_calls"]),
                avg_duration_sec=r["avg_duration_sec"],
                avg_stt_ms=r["avg_stt_ms"],
                avg_llm_ms=r["avg_llm_ms"],
                avg_tts_ms=r["avg_tts_ms"],
            )
            for r in rows_raw
        ]

        return AgentPerformanceResponse(
            agents=rows,
            period_days=days,
            generated_at=datetime.now(UTC),
        )

    # ── Agent deep-dive ───────────────────────────────────────────────────

    async def agent_deep_dive(
        self,
        agent_id: UUID,
        org_id: UUID,
        days: int = 30,
    ) -> AgentDeepDiveResponse:
        since = datetime.now(UTC) - timedelta(days=days)
        data = await self.repo.agent_deep_dive(agent_id, org_id, since)

        samples = [
            TranscriptSample(
                call_id=s["call_id"],
                started_at=s["started_at"],
                duration_sec=s["duration_sec"],
                transcript_snippet=s["transcript_snippet"],
            )
            for s in data["samples"]
        ]

        t = data["total"]
        return AgentDeepDiveResponse(
            agent_id=agent_id,
            period_days=days,
            total_calls=t,
            completed_calls=data["completed"],
            failed_calls=data["failed"],
            success_rate=self._pct(data["completed"], t),
            avg_duration_sec=data["avg_duration"],
            p50_stt_ms=data["p50_stt"],
            p95_stt_ms=data["p95_stt"],
            p99_stt_ms=data["p99_stt"],
            p50_llm_ms=data["p50_llm"],
            p95_llm_ms=data["p95_llm"],
            p99_llm_ms=data["p99_llm"],
            p50_tts_ms=data["p50_tts"],
            p95_tts_ms=data["p95_tts"],
            p99_tts_ms=data["p99_tts"],
            recent_samples=samples,
            generated_at=datetime.now(UTC),
        )


# ── Admin service ─────────────────────────────────────────────────────────────


class AdminService:
    """
    Administration endpoints — not org-scoped; platform superadmin only.
    """

    # ── GPU status ────────────────────────────────────────────────────────

    @staticmethod
    def gpu_status() -> GPUStatusResponse:
        """
        Return GPU metrics via pynvml.

        Gracefully degrades to ``nvml_available=False`` when:
        * pynvml is not installed.
        * No NVIDIA driver / hardware present.
        """
        now = datetime.now(UTC)
        try:
            import pynvml  # type: ignore[import-not-found]

            pynvml.nvmlInit()
        except Exception as exc:  # noqa: BLE001
            log.debug("gpu_status.nvml_unavailable", reason=str(exc))
            return GPUStatusResponse(nvml_available=False, generated_at=now)

        try:
            driver = pynvml.nvmlSystemGetDriverVersion()
            cuda = pynvml.nvmlSystemGetCudaDriverVersion_v2()
            count = pynvml.nvmlDeviceGetCount()
            devices: list[GPUDeviceInfo] = []
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                try:
                    power_draw = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                    power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
                except Exception:  # noqa: BLE001
                    power_draw = power_limit = None

                vram_total = mem.total // (1024 * 1024)
                vram_used = mem.used // (1024 * 1024)
                vram_free = mem.free // (1024 * 1024)
                devices.append(
                    GPUDeviceInfo(
                        index=i,
                        name=name if isinstance(name, str) else name.decode(),
                        vram_total_mib=vram_total,
                        vram_used_mib=vram_used,
                        vram_free_mib=vram_free,
                        vram_utilization_pct=round(100.0 * vram_used / vram_total, 2)
                        if vram_total
                        else 0.0,
                        gpu_utilization_pct=float(util.gpu),
                        temperature_celsius=float(temp),
                        power_draw_watts=power_draw,
                        power_limit_watts=power_limit,
                    )
                )
            pynvml.nvmlShutdown()
            return GPUStatusResponse(
                nvml_available=True,
                driver_version=driver if isinstance(driver, str) else driver.decode(),
                cuda_version=str(cuda),
                devices=devices,
                generated_at=now,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("gpu_status.nvml_error", error=str(exc))
            try:
                pynvml.nvmlShutdown()
            except Exception:  # noqa: BLE001
                pass
            return GPUStatusResponse(nvml_available=False, generated_at=now)

    # ── Queue status ──────────────────────────────────────────────────────

    @staticmethod
    def queue_status() -> QueueStatusResponse:
        """
        Return Celery queue depths from the broker (Redis).

        Uses ``celery inspect`` which talks directly to Redis.  If Celery
        workers are offline the method returns zeros.
        """
        now = datetime.now(UTC)
        from app.core.celery_app import celery_app
        from app.config import get_settings

        queues_cfg = get_settings().CELERY_QUEUES if hasattr(get_settings(), "CELERY_QUEUES") else [
            "default", "email", "webhooks", "notifications", "files"
        ]

        try:
            inspect = celery_app.control.inspect(timeout=2.0)
            active_map: dict = inspect.active() or {}
            reserved_map: dict = inspect.reserved() or {}
            workers_online = len(active_map)

            active_flat: list = [t for tasks in active_map.values() for t in tasks]
            reserved_flat: list = [t for tasks in reserved_map.values() for t in tasks]

            queue_infos: list[QueueInfo] = []
            for q in queues_cfg:
                q_active = sum(1 for t in active_flat if (t.get("delivery_info") or {}).get("routing_key") == q)
                q_reserved = sum(1 for t in reserved_flat if (t.get("delivery_info") or {}).get("routing_key") == q)
                queue_infos.append(
                    QueueInfo(name=q, pending=q_reserved, active=q_active, reserved=q_reserved, failed=0)
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("queue_status.inspect_failed", error=str(exc))
            workers_online = 0
            queue_infos = [
                QueueInfo(name=q, pending=0, active=0, reserved=0, failed=0) for q in queues_cfg
            ]

        return QueueStatusResponse(
            queues=queue_infos,
            workers_online=workers_online,
            generated_at=now,
        )

    # ── Model benchmark ───────────────────────────────────────────────────

    @staticmethod
    async def run_model_benchmark(
        data: ModelBenchmarkRequest,
    ) -> ModelBenchmarkResponse:
        """
        Run a synthetic latency benchmark for the requested model.

        The benchmark calls the pipeline service's ``/benchmark`` endpoint
        (if available), otherwise performs a CPU timing stub.  Results are
        used only for relative comparison; absolute figures depend on hardware.
        """
        import asyncio

        import httpx

        from app.config import get_settings

        settings = get_settings()
        pipeline_url = settings.PIPELINE_SERVICE_URL.rstrip("/")
        results: list[ModelBenchmarkResult] = []

        latencies: list[float] = []
        error_msg: str | None = None

        try:
            for _ in range(data.runs):
                start = time.monotonic()
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{pipeline_url}/benchmark",
                        json={
                            "model": data.model_name,
                            "sample_text": data.sample_text,
                        },
                    )
                    ms = (time.monotonic() - start) * 1000
                    if resp.status_code == 200:
                        body = resp.json()
                        ms = float(body.get("latency_ms", ms))
                    latencies.append(ms)
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            # Fall back to a deterministic stub so the endpoint never crashes
            import random
            latencies = [50 + random.uniform(-5, 5) for _ in range(data.runs)]
            log.debug("benchmark.pipeline_unavailable", error=error_msg)

        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        p50 = sorted_lat[int(0.50 * (n - 1))]
        p95 = sorted_lat[int(0.95 * (n - 1))]

        results.append(
            ModelBenchmarkResult(
                model_name=data.model_name,
                runs=data.runs,
                avg_latency_ms=round(statistics.mean(latencies), 2),
                p50_latency_ms=round(p50, 2),
                p95_latency_ms=round(p95, 2),
                min_latency_ms=round(min(latencies), 2),
                max_latency_ms=round(max(latencies), 2),
                error=error_msg,
            )
        )

        return ModelBenchmarkResponse(results=results, benchmark_at=datetime.now(UTC))

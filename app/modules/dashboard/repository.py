"""
Dashboard module — analytics repository.

All queries run against the ``call_logs`` table.  Heavy aggregations use a
single SQL round-trip where possible.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Float, Integer, String, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent, CallLog

log = structlog.get_logger(__name__)


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Overview ──────────────────────────────────────────────────────────

    async def monthly_summary(self, org_id: UUID, since: datetime) -> dict[str, Any]:
        """
        Return aggregate call counts and duration for the current period.

        ``since`` should be the first moment of the current billing month.
        """
        result = await self.session.execute(
            select(
                func.count().label("total"),
                func.count()
                .filter(CallLog.status == "completed")
                .label("completed"),
                func.count()
                .filter(CallLog.status == "failed")
                .label("failed"),
                func.coalesce(func.sum(CallLog.duration_sec), 0).label("total_duration_sec"),
            ).where(
                CallLog.org_id == org_id,
                CallLog.created_at >= since,
            )
        )
        row = result.one()
        return {
            "total": int(row.total or 0),
            "completed": int(row.completed or 0),
            "failed": int(row.failed or 0),
            "total_duration_sec": int(row.total_duration_sec or 0),
        }

    async def top_agents(
        self,
        org_id: UUID,
        since: datetime,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return the top *limit* agents ranked by call volume for the period."""
        stmt = (
            select(
                CallLog.agent_id.label("agent_id"),
                Agent.name.label("agent_name"),
                func.count().label("total_calls"),
                func.count()
                .filter(CallLog.status == "completed")
                .label("completed"),
                func.avg(cast(CallLog.duration_sec, Float)).label("avg_duration"),
            )
            .join(Agent, Agent.id == CallLog.agent_id)
            .where(
                CallLog.org_id == org_id,
                CallLog.created_at >= since,
            )
            .group_by(CallLog.agent_id, Agent.name)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "agent_id": r.agent_id,
                "agent_name": r.agent_name,
                "total_calls": int(r.total_calls or 0),
                "completed": int(r.completed or 0),
                "avg_duration": float(r.avg_duration) if r.avg_duration is not None else None,
            }
            for r in rows
        ]

    # ── Latency 24h ───────────────────────────────────────────────────────

    async def latency_summary(self, org_id: UUID, since: datetime) -> dict[str, Any]:
        """Return P50/P95/P99 for STT / LLM / TTS over the window."""
        result = await self.session.execute(
            select(
                func.count().label("samples"),
                # STT
                func.percentile_cont(0.5)
                .within_group(CallLog.stt_ms.asc())
                .label("p50_stt"),
                func.percentile_cont(0.95)
                .within_group(CallLog.stt_ms.asc())
                .label("p95_stt"),
                func.percentile_cont(0.99)
                .within_group(CallLog.stt_ms.asc())
                .label("p99_stt"),
                # LLM
                func.percentile_cont(0.5)
                .within_group(CallLog.llm_ttft_ms.asc())
                .label("p50_llm"),
                func.percentile_cont(0.95)
                .within_group(CallLog.llm_ttft_ms.asc())
                .label("p95_llm"),
                func.percentile_cont(0.99)
                .within_group(CallLog.llm_ttft_ms.asc())
                .label("p99_llm"),
                # TTS
                func.percentile_cont(0.5)
                .within_group(CallLog.tts_ttfb_ms.asc())
                .label("p50_tts"),
                func.percentile_cont(0.95)
                .within_group(CallLog.tts_ttfb_ms.asc())
                .label("p95_tts"),
                func.percentile_cont(0.99)
                .within_group(CallLog.tts_ttfb_ms.asc())
                .label("p99_tts"),
            ).where(
                CallLog.org_id == org_id,
                CallLog.created_at >= since,
                CallLog.stt_ms.is_not(None),
            )
        )
        row = result.one()
        return {
            "samples": int(row.samples or 0),
            "p50_stt": _f(row.p50_stt),
            "p95_stt": _f(row.p95_stt),
            "p99_stt": _f(row.p99_stt),
            "p50_llm": _f(row.p50_llm),
            "p95_llm": _f(row.p95_llm),
            "p99_llm": _f(row.p99_llm),
            "p50_tts": _f(row.p50_tts),
            "p95_tts": _f(row.p95_tts),
            "p99_tts": _f(row.p99_tts),
        }

    async def latency_hourly_buckets(
        self, org_id: UUID, since: datetime
    ) -> list[dict[str, Any]]:
        """
        Return hourly latency percentiles for the last 24 h.

        Uses ``date_trunc('hour', created_at)`` to form buckets so the client
        can render a time-series chart with 24 data points.
        """
        stmt = text(
            """
            SELECT
                date_trunc('hour', created_at) AS bucket,
                COUNT(*) AS cnt,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY stt_ms) AS p50_stt,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY stt_ms) AS p95_stt,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY stt_ms) AS p99_stt,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY llm_ttft_ms) AS p50_llm,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY llm_ttft_ms) AS p95_llm,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY llm_ttft_ms) AS p99_llm,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tts_ttfb_ms) AS p50_tts,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY tts_ttfb_ms) AS p95_tts,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY tts_ttfb_ms) AS p99_tts
            FROM call_logs
            WHERE org_id = :org_id AND created_at >= :since
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        )
        rows = (
            await self.session.execute(stmt, {"org_id": str(org_id), "since": since})
        ).all()
        return [
            {
                "label": row.bucket.isoformat() if row.bucket else "",
                "sample_count": int(row.cnt or 0),
                "p50_stt": _f(row.p50_stt),
                "p95_stt": _f(row.p95_stt),
                "p99_stt": _f(row.p99_stt),
                "p50_llm": _f(row.p50_llm),
                "p95_llm": _f(row.p95_llm),
                "p99_llm": _f(row.p99_llm),
                "p50_tts": _f(row.p50_tts),
                "p95_tts": _f(row.p95_tts),
                "p99_tts": _f(row.p99_tts),
            }
            for row in rows
        ]

    # ── Call volume ───────────────────────────────────────────────────────

    async def call_volume(
        self,
        org_id: UUID,
        granularity: str,
        since: datetime,
    ) -> list[dict[str, Any]]:
        """
        Return call volume grouped by *granularity* (hour | day | month).
        """
        trunc = {"hour": "hour", "day": "day", "month": "month"}.get(granularity, "day")
        stmt = text(
            f"""
            SELECT
                date_trunc('{trunc}', created_at) AS bucket,
                COUNT(*) AS total_calls,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COALESCE(SUM(duration_sec), 0) AS total_duration,
                COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound,
                COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound
            FROM call_logs
            WHERE org_id = :org_id AND created_at >= :since
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        )
        rows = (
            await self.session.execute(stmt, {"org_id": str(org_id), "since": since})
        ).all()
        return [
            {
                "label": row.bucket.strftime(_label_fmt(granularity)) if row.bucket else "",
                "total_calls": int(row.total_calls or 0),
                "completed_calls": int(row.completed or 0),
                "failed_calls": int(row.failed or 0),
                "total_duration_sec": int(row.total_duration or 0),
                "inbound_calls": int(row.inbound or 0),
                "outbound_calls": int(row.outbound or 0),
            }
            for row in rows
        ]

    # ── Agent performance ─────────────────────────────────────────────────

    async def agent_performance(
        self,
        org_id: UUID,
        since: datetime,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(
                CallLog.agent_id,
                Agent.name.label("agent_name"),
                func.count().label("total"),
                func.count().filter(CallLog.status == "completed").label("completed"),
                func.count().filter(CallLog.status == "failed").label("failed"),
                func.avg(cast(CallLog.duration_sec, Float)).label("avg_duration"),
                func.avg(cast(CallLog.stt_ms, Float)).label("avg_stt"),
                func.avg(cast(CallLog.llm_ttft_ms, Float)).label("avg_llm"),
                func.avg(cast(CallLog.tts_ttfb_ms, Float)).label("avg_tts"),
            )
            .join(Agent, Agent.id == CallLog.agent_id)
            .where(
                CallLog.org_id == org_id,
                CallLog.created_at >= since,
            )
            .group_by(CallLog.agent_id, Agent.name)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "agent_id": r.agent_id,
                "agent_name": r.agent_name,
                "total_calls": int(r.total or 0),
                "completed_calls": int(r.completed or 0),
                "failed_calls": int(r.failed or 0),
                "avg_duration_sec": _f(r.avg_duration),
                "avg_stt_ms": _f(r.avg_stt),
                "avg_llm_ms": _f(r.avg_llm),
                "avg_tts_ms": _f(r.avg_tts),
            }
            for r in rows
        ]

    # ── Agent deep-dive ───────────────────────────────────────────────────

    async def agent_deep_dive(
        self,
        agent_id: UUID,
        org_id: UUID,
        since: datetime,
    ) -> dict[str, Any]:
        agg_stmt = select(
            func.count().label("total"),
            func.count().filter(CallLog.status == "completed").label("completed"),
            func.count().filter(CallLog.status == "failed").label("failed"),
            func.avg(cast(CallLog.duration_sec, Float)).label("avg_duration"),
            func.percentile_cont(0.5).within_group(CallLog.stt_ms.asc()).label("p50_stt"),
            func.percentile_cont(0.95).within_group(CallLog.stt_ms.asc()).label("p95_stt"),
            func.percentile_cont(0.99).within_group(CallLog.stt_ms.asc()).label("p99_stt"),
            func.percentile_cont(0.5).within_group(CallLog.llm_ttft_ms.asc()).label("p50_llm"),
            func.percentile_cont(0.95).within_group(CallLog.llm_ttft_ms.asc()).label("p95_llm"),
            func.percentile_cont(0.99).within_group(CallLog.llm_ttft_ms.asc()).label("p99_llm"),
            func.percentile_cont(0.5).within_group(CallLog.tts_ttfb_ms.asc()).label("p50_tts"),
            func.percentile_cont(0.95).within_group(CallLog.tts_ttfb_ms.asc()).label("p95_tts"),
            func.percentile_cont(0.99).within_group(CallLog.tts_ttfb_ms.asc()).label("p99_tts"),
        ).where(
            CallLog.agent_id == agent_id,
            CallLog.org_id == org_id,
            CallLog.created_at >= since,
        )

        row = (await self.session.execute(agg_stmt)).one()

        # Recent transcript samples
        samples_stmt = (
            select(CallLog)
            .where(
                CallLog.agent_id == agent_id,
                CallLog.org_id == org_id,
                CallLog.created_at >= since,
                CallLog.transcript.is_not(None),
            )
            .order_by(CallLog.created_at.desc())
            .limit(5)
        )
        sample_rows = (await self.session.execute(samples_stmt)).scalars().all()

        return {
            "total": int(row.total or 0),
            "completed": int(row.completed or 0),
            "failed": int(row.failed or 0),
            "avg_duration": _f(row.avg_duration),
            "p50_stt": _f(row.p50_stt),
            "p95_stt": _f(row.p95_stt),
            "p99_stt": _f(row.p99_stt),
            "p50_llm": _f(row.p50_llm),
            "p95_llm": _f(row.p95_llm),
            "p99_llm": _f(row.p99_llm),
            "p50_tts": _f(row.p50_tts),
            "p95_tts": _f(row.p95_tts),
            "p99_tts": _f(row.p99_tts),
            "samples": [
                {
                    "call_id": s.id,
                    "started_at": s.started_at,
                    "duration_sec": s.duration_sec,
                    "transcript_snippet": (s.transcript or "")[:200],
                }
                for s in sample_rows
            ],
        }


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(v: object) -> float | None:
    return round(float(v), 2) if v is not None else None


def _label_fmt(granularity: str) -> str:
    return {"hour": "%Y-%m-%dT%H:00", "day": "%Y-%m-%d", "month": "%Y-%m"}.get(
        granularity, "%Y-%m-%d"
    )

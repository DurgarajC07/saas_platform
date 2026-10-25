"""
Agents module repositories.

AgentRepository          — CRUD + soft-delete for the agents table.
AgentPhoneNumberRepository — CRUD for agent_phone_numbers.
CallLogRepository        — Append-only writes + analytics queries for call_logs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Float, cast, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent, AgentPhoneNumber, CallLog


# ── AgentRepository ─────────────────────────────────────────────────────────


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Create ─────────────────────────────────────────────────────────────

    async def create(self, **kwargs: Any) -> Agent:
        agent = Agent(**kwargs)
        self.session.add(agent)
        await self.session.flush()
        await self.session.refresh(agent)
        return agent

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_org(self, agent_id: UUID, org_id: UUID) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.org_id == org_id,
                Agent.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_slug_and_org(self, slug: str, org_id: UUID) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(
                Agent.slug == slug,
                Agent.org_id == org_id,
                Agent.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        status: str | None = None,
        agent_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Agent], int]:
        stmt = select(Agent).where(
            Agent.org_id == org_id, Agent.deleted_at.is_(None)
        )
        if status:
            stmt = stmt.where(Agent.status == status)
        if agent_type:
            stmt = stmt.where(Agent.agent_type == agent_type)
        stmt = stmt.order_by(Agent.created_at.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(stmt.offset(offset).limit(limit))
        ).scalars().all()
        return list(rows), total

    # ── Update ─────────────────────────────────────────────────────────────

    async def update(self, agent_id: UUID, **kwargs: Any) -> Agent | None:
        await self.session.execute(
            update(Agent)
            .where(Agent.id == agent_id, Agent.deleted_at.is_(None))
            .values(**kwargs)
        )
        await self.session.flush()
        return await self.get_by_id(agent_id)

    # ── Soft delete ────────────────────────────────────────────────────────

    async def soft_delete(self, agent_id: UUID) -> bool:
        result = await self.session.execute(
            update(Agent)
            .where(Agent.id == agent_id, Agent.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC), status="archived")
        )
        await self.session.flush()
        return result.rowcount > 0


# ── AgentPhoneNumberRepository ───────────────────────────────────────────────


class AgentPhoneNumberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> AgentPhoneNumber:
        pn = AgentPhoneNumber(**kwargs)
        self.session.add(pn)
        await self.session.flush()
        await self.session.refresh(pn)
        return pn

    async def get_by_number(self, phone_number: str) -> AgentPhoneNumber | None:
        result = await self.session.execute(
            select(AgentPhoneNumber).where(
                AgentPhoneNumber.phone_number == phone_number
            )
        )
        return result.scalar_one_or_none()

    async def list_by_agent(self, agent_id: UUID) -> list[AgentPhoneNumber]:
        rows = (
            await self.session.execute(
                select(AgentPhoneNumber)
                .where(AgentPhoneNumber.agent_id == agent_id)
                .order_by(AgentPhoneNumber.created_at.desc())
            )
        ).scalars().all()
        return list(rows)

    async def get_by_id_and_agent(
        self, phone_number_id: UUID, agent_id: UUID
    ) -> AgentPhoneNumber | None:
        result = await self.session.execute(
            select(AgentPhoneNumber).where(
                AgentPhoneNumber.id == phone_number_id,
                AgentPhoneNumber.agent_id == agent_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, phone_number_id: UUID) -> None:
        await self.session.execute(
            delete(AgentPhoneNumber).where(AgentPhoneNumber.id == phone_number_id)
        )
        await self.session.flush()


# ── CallLogRepository ────────────────────────────────────────────────────────


class CallLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> CallLog:
        log = CallLog(**kwargs)
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log

    async def get_by_id(self, call_id: UUID) -> CallLog | None:
        result = await self.session.execute(
            select(CallLog).where(CallLog.id == call_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_org(self, call_id: UUID, org_id: UUID) -> CallLog | None:
        result = await self.session.execute(
            select(CallLog).where(
                CallLog.id == call_id,
                CallLog.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_agent(
        self,
        agent_id: UUID,
        org_id: UUID,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CallLog], int]:
        stmt = select(CallLog).where(
            CallLog.agent_id == agent_id,
            CallLog.org_id == org_id,
        )
        if status:
            stmt = stmt.where(CallLog.status == status)
        stmt = stmt.order_by(CallLog.created_at.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(stmt.offset(offset).limit(limit))
        ).scalars().all()
        return list(rows), total

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        status: str | None = None,
        agent_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CallLog], int]:
        """Org-wide call history (across all agents) for the global calls page."""
        stmt = select(CallLog).where(CallLog.org_id == org_id)
        if status:
            stmt = stmt.where(CallLog.status == status)
        if agent_id:
            stmt = stmt.where(CallLog.agent_id == agent_id)
        stmt = stmt.order_by(CallLog.created_at.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(stmt.offset(offset).limit(limit))
        ).scalars().all()
        return list(rows), total

    async def get_analytics(
        self,
        agent_id: UUID,
        org_id: UUID,
        since: datetime,
    ) -> dict[str, Any]:
        """
        Return aggregated latency and volume stats for *agent_id* since *since*.

        Uses a single SQL query for efficiency.
        """
        agg = (
            await self.session.execute(
                select(
                    func.count().label("total"),
                    func.count()
                    .filter(CallLog.status == "completed")
                    .label("completed"),
                    func.count()
                    .filter(CallLog.status == "failed")
                    .label("failed"),
                    func.count()
                    .filter(CallLog.direction == "inbound")
                    .label("inbound"),
                    func.count()
                    .filter(CallLog.direction == "outbound")
                    .label("outbound"),
                    func.sum(CallLog.duration_sec).label("total_duration"),
                    func.avg(cast(CallLog.duration_sec, Float)).label("avg_duration"),
                    # STT
                    func.avg(cast(CallLog.stt_ms, Float)).label("avg_stt"),
                    func.percentile_cont(0.5)
                    .within_group(CallLog.stt_ms.asc())
                    .label("p50_stt"),
                    func.percentile_cont(0.95)
                    .within_group(CallLog.stt_ms.asc())
                    .label("p95_stt"),
                    func.min(CallLog.stt_ms).label("min_stt"),
                    func.max(CallLog.stt_ms).label("max_stt"),
                    # LLM TTFT
                    func.avg(cast(CallLog.llm_ttft_ms, Float)).label("avg_llm"),
                    func.percentile_cont(0.5)
                    .within_group(CallLog.llm_ttft_ms.asc())
                    .label("p50_llm"),
                    func.percentile_cont(0.95)
                    .within_group(CallLog.llm_ttft_ms.asc())
                    .label("p95_llm"),
                    func.min(CallLog.llm_ttft_ms).label("min_llm"),
                    func.max(CallLog.llm_ttft_ms).label("max_llm"),
                    # TTS TTFB
                    func.avg(cast(CallLog.tts_ttfb_ms, Float)).label("avg_tts"),
                    func.percentile_cont(0.5)
                    .within_group(CallLog.tts_ttfb_ms.asc())
                    .label("p50_tts"),
                    func.percentile_cont(0.95)
                    .within_group(CallLog.tts_ttfb_ms.asc())
                    .label("p95_tts"),
                    func.min(CallLog.tts_ttfb_ms).label("min_tts"),
                    func.max(CallLog.tts_ttfb_ms).label("max_tts"),
                ).where(
                    CallLog.agent_id == agent_id,
                    CallLog.org_id == org_id,
                    CallLog.created_at >= since,
                )
            )
        ).mappings().one()

        return dict(agg)

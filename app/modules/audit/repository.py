"""
Audit repository — data-access for audit_logs table.

Never raises for logging (callers guard with try/except).
Filtering is intentionally flexible to support admin dashboards.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Write ───────────────────────────────────────────────────────────

    async def create(self, **kwargs: Any) -> AuditLog:
        entry = AuditLog(**kwargs)
        self.session.add(entry)
        await self.session.flush()
        return entry

    # ── Read ────────────────────────────────────────────────────────────

    async def get_by_id(self, log_id: UUID) -> AuditLog | None:
        result = await self.session.execute(
            select(AuditLog).where(AuditLog.id == log_id)
        )
        return result.scalar_one_or_none()

    async def list_with_filters(
        self,
        *,
        org_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Return (rows, total_count) applying all provided filters."""
        base_q = select(AuditLog)

        if org_id is not None:
            base_q = base_q.where(AuditLog.organization_id == org_id)
        if actor_user_id is not None:
            base_q = base_q.where(AuditLog.actor_user_id == actor_user_id)
        if action is not None:
            base_q = base_q.where(AuditLog.action.ilike(f"%{action}%"))
        if resource_type is not None:
            base_q = base_q.where(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            base_q = base_q.where(AuditLog.resource_id == resource_id)
        if start_date is not None:
            base_q = base_q.where(AuditLog.created_at >= start_date)
        if end_date is not None:
            base_q = base_q.where(AuditLog.created_at <= end_date)

        count_q = select(func.count()).select_from(base_q.subquery())
        total: int = (await self.session.execute(count_q)).scalar_one()

        rows_q = (
            base_q.order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self.session.execute(rows_q)).scalars().all())
        return rows, total

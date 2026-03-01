"""
Security module repositories — login_attempts and blocked_ips.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.security.models import BlockedIP, LoginAttempt


# ── LoginAttemptRepository ──────────────────────────────────────────────

class LoginAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> LoginAttempt:
        kwargs.setdefault("attempted_at", datetime.now(UTC))
        attempt = LoginAttempt(**kwargs)
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def count_failures_from_ip(self, ip: str, *, hours: int = 1) -> int:
        """Count failed login attempts from ip in the past N hours."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.count())
            .where(LoginAttempt.ip_address == ip)
            .where(LoginAttempt.is_success == False)  # noqa: E712
            .where(LoginAttempt.attempted_at >= since)
        )
        return result.scalar_one()

    async def list_with_filters(
        self,
        *,
        ip_address: str | None = None,
        email: str | None = None,
        user_id: UUID | None = None,
        is_success: bool | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[LoginAttempt], int]:
        base_q = select(LoginAttempt)
        if ip_address is not None:
            base_q = base_q.where(LoginAttempt.ip_address == ip_address)
        if email is not None:
            base_q = base_q.where(LoginAttempt.email.ilike(f"%{email}%"))
        if user_id is not None:
            base_q = base_q.where(LoginAttempt.user_id == user_id)
        if is_success is not None:
            base_q = base_q.where(LoginAttempt.is_success == is_success)
        if start_date is not None:
            base_q = base_q.where(LoginAttempt.attempted_at >= start_date)
        if end_date is not None:
            base_q = base_q.where(LoginAttempt.attempted_at <= end_date)

        count_q = select(func.count()).select_from(base_q.subquery())
        total: int = (await self.session.execute(count_q)).scalar_one()

        rows_q = base_q.order_by(LoginAttempt.attempted_at.desc()).limit(limit).offset(offset)
        rows = list((await self.session.execute(rows_q)).scalars().all())
        return rows, total


# ── BlockedIPRepository ─────────────────────────────────────────────────

class BlockedIPRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> BlockedIP:
        record = BlockedIP(**kwargs)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_ip(self, ip: str) -> BlockedIP | None:
        result = await self.session.execute(
            select(BlockedIP).where(BlockedIP.ip_address == ip)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, blocked_id: UUID) -> BlockedIP | None:
        result = await self.session.execute(
            select(BlockedIP).where(BlockedIP.id == blocked_id)
        )
        return result.scalar_one_or_none()

    async def list_active(
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[BlockedIP], int]:
        base_q = select(BlockedIP).where(BlockedIP.is_active == True)  # noqa: E712
        count_q = select(func.count()).select_from(base_q.subquery())
        total: int = (await self.session.execute(count_q)).scalar_one()
        rows_q = base_q.order_by(BlockedIP.created_at.desc()).limit(limit).offset(offset)
        rows = list((await self.session.execute(rows_q)).scalars().all())
        return rows, total

    async def deactivate(self, blocked_id: UUID) -> bool:
        result = await self.session.execute(
            update(BlockedIP)
            .where(BlockedIP.id == blocked_id)
            .values(is_active=False)
            .returning(BlockedIP.id)
        )
        await self.session.flush()
        return result.scalar_one_or_none() is not None

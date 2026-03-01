"""
Security service.

Responsibilities:
  - Record every login attempt.
  - Auto-block an IP after 50 failures / 1 hour (Redis fast-path).
  - Manual IP block / unblock (admin).
  - Expose paginated attempt log and security-event aggregation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.core.pagination import PaginationParams, paginate
from app.modules.auth.models import User
from app.modules.security.models import BlockedIP, LoginAttempt
from app.modules.security.repository import BlockedIPRepository, LoginAttemptRepository
from app.modules.security.schemas import (
    BlockIPRequest,
    BlockedIPListResponse,
    BlockedIPResponse,
    LoginAttemptListResponse,
    LoginAttemptResponse,
    SecurityEventResponse,
)

logger = structlog.get_logger(__name__)

_BLOCKED_IP_PREFIX = "blocked_ip:"
_AUTO_BLOCK_FAILURES = 50
_AUTO_BLOCK_WINDOW_HOURS = 1
_AUTO_BLOCK_DURATION_HOURS = 24


class SecurityService:
    def __init__(self, session: AsyncSession, redis: aioredis.Redis) -> None:
        self.session = session
        self.redis = redis
        self.attempt_repo = LoginAttemptRepository(session)
        self.blocked_repo = BlockedIPRepository(session)

    # ── Redis helpers ────────────────────────────────────────────────────

    def _blocked_key(self, ip: str) -> str:
        return f"{_BLOCKED_IP_PREFIX}{ip}"

    async def _set_redis_block(self, ip: str, hours: int | None) -> None:
        key = self._blocked_key(ip)
        if hours:
            await self.redis.setex(key, hours * 3600, "1")
        else:
            await self.redis.set(key, "1")  # permanent until manually unblocked

    async def _clear_redis_block(self, ip: str) -> None:
        await self.redis.delete(self._blocked_key(ip))

    async def is_ip_blocked(self, ip: str) -> bool:
        """Fast Redis-first check (used by IPBlockMiddleware)."""
        if await self.redis.get(self._blocked_key(ip)):
            return True
        # Fallback: check DB for active blocks (warm Redis cache)
        record = await self.blocked_repo.get_by_ip(ip)
        if record and record.is_active:
            if record.blocked_until is None or record.blocked_until > datetime.now(UTC):
                await self._set_redis_block(ip, None)
                return True
            # Expired — deactivate lazily
            await self.blocked_repo.deactivate(record.id)
        return False

    # ── Login attempt recording ──────────────────────────────────────────

    async def record_login_attempt(
        self,
        *,
        email: str,
        ip: str,
        ua: str | None = None,
        success: bool,
        failure_reason: str | None = None,
        user_id: UUID | None = None,
        method: str = "password",
    ) -> None:
        """
        Persist the attempt.  On failure, auto-block the IP if it has
        exceeded _AUTO_BLOCK_FAILURES in the past _AUTO_BLOCK_WINDOW_HOURS.
        """
        try:
            await self.attempt_repo.create(
                email=email,
                ip_address=ip,
                user_agent=ua,
                is_success=success,
                failure_reason=failure_reason,
                user_id=user_id,
                method=method,
            )

            if not success:
                count = await self.attempt_repo.count_failures_from_ip(
                    ip, hours=_AUTO_BLOCK_WINDOW_HOURS
                )
                if count >= _AUTO_BLOCK_FAILURES:
                    await self._auto_block_ip(ip)
        except Exception as exc:  # noqa: BLE001
            logger.error("security.record_attempt_failed", ip=ip, error=str(exc))

    async def check_and_autoblock(self, ip: str) -> None:
        """
        Called by AuthService after recording a failed login.
        Counts failures in the last hour; auto-blocks if >= threshold.
        Never raises — failure must not block the auth response.
        """
        try:
            count = await self.attempt_repo.count_failures_from_ip(
                ip, hours=_AUTO_BLOCK_WINDOW_HOURS
            )
            if count >= _AUTO_BLOCK_FAILURES:
                await self._auto_block_ip(ip)
        except Exception as exc:  # noqa: BLE001
            logger.error("security.check_autoblock_failed", ip=ip, error=str(exc))

    async def _auto_block_ip(self, ip: str) -> None:
        """Block the IP automatically; idempotent if already blocked."""
        existing = await self.blocked_repo.get_by_ip(ip)
        if existing and existing.is_active:
            return
        blocked_until = datetime.now(UTC) + timedelta(hours=_AUTO_BLOCK_DURATION_HOURS)
        if existing:
            # Re-activate the existing record
            existing.is_active = True
            existing.blocked_until = blocked_until
            existing.reason = "Auto-blocked: too many failed attempts"
            await self.session.flush()
        else:
            await self.blocked_repo.create(
                ip_address=ip,
                reason="Auto-blocked: too many failed attempts",
                blocked_by=None,
                blocked_until=blocked_until,
                is_active=True,
            )
        await self._set_redis_block(ip, _AUTO_BLOCK_DURATION_HOURS)
        logger.warning("security.ip_auto_blocked", ip=ip, hours=_AUTO_BLOCK_DURATION_HOURS)

    # ── Manual IP block / unblock ────────────────────────────────────────

    async def block_ip(
        self,
        data: BlockIPRequest,
        actor: User,
    ) -> BlockedIPResponse:
        _require_platform_admin(actor)
        ip = str(data.ip_address)
        existing = await self.blocked_repo.get_by_ip(ip)
        blocked_until: datetime | None = None
        if data.hours:
            blocked_until = datetime.now(UTC) + timedelta(hours=data.hours)

        if existing and existing.is_active:
            raise ConflictException(f"IP {ip} is already blocked")

        if existing:
            existing.is_active = True
            existing.blocked_by = actor.id
            existing.blocked_until = blocked_until
            existing.reason = data.reason
            await self.session.flush()
            record = existing
        else:
            record = await self.blocked_repo.create(
                ip_address=ip,
                reason=data.reason,
                blocked_by=actor.id,
                blocked_until=blocked_until,
                is_active=True,
            )
        await self._set_redis_block(ip, data.hours)
        logger.info("security.ip_manually_blocked", ip=ip, actor_id=str(actor.id))
        return BlockedIPResponse.model_validate(record)

    async def unblock_ip(
        self,
        blocked_id: UUID,
        actor: User,
    ) -> None:
        _require_platform_admin(actor)
        record = await self.blocked_repo.get_by_id(blocked_id)
        if not record:
            raise NotFoundException("Blocked IP record not found")
        await self.blocked_repo.deactivate(blocked_id)
        await self._clear_redis_block(str(record.ip_address))
        logger.info("security.ip_unblocked", ip=str(record.ip_address), actor_id=str(actor.id))

    # ── Queries ──────────────────────────────────────────────────────────

    async def list_login_attempts(
        self,
        params: PaginationParams,
        *,
        ip_address: str | None = None,
        email: str | None = None,
        user_id: UUID | None = None,
        is_success: bool | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> LoginAttemptListResponse:
        rows, total = await self.attempt_repo.list_with_filters(
            ip_address=ip_address,
            email=email,
            user_id=user_id,
            is_success=is_success,
            start_date=start_date,
            end_date=end_date,
            limit=params.limit,
            offset=params.offset,
        )
        return LoginAttemptListResponse(
            attempts=[LoginAttemptResponse.model_validate(r) for r in rows],
            pagination=paginate(total, params),
        )

    async def list_blocked_ips(
        self,
        params: PaginationParams,
    ) -> BlockedIPListResponse:
        rows, total = await self.blocked_repo.list_active(
            limit=params.limit, offset=params.offset
        )
        return BlockedIPListResponse(
            blocked_ips=[BlockedIPResponse.model_validate(r) for r in rows],
            pagination=paginate(total, params),
        )

    async def list_security_events(
        self,
        *,
        hours: int = 24,
        min_failures: int = 5,
        limit: int = 50,
    ) -> list[SecurityEventResponse]:
        """
        Aggregate suspicious IPs: those with >= min_failures failed logins
        in the past N hours. Returns a dashboard-ready event list.
        """
        since = datetime.now(UTC) - timedelta(hours=hours)

        # Raw SQL aggregation using SQLAlchemy core
        stmt = (
            select(
                LoginAttempt.ip_address,
                func.count().label("failure_count"),
                func.min(LoginAttempt.attempted_at).label("first_seen"),
                func.max(LoginAttempt.attempted_at).label("last_seen"),
            )
            .where(LoginAttempt.is_success == False)  # noqa: E712
            .where(LoginAttempt.attempted_at >= since)
            .group_by(LoginAttempt.ip_address)
            .having(func.count() >= min_failures)
            .order_by(func.count().desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        # Batch-check which IPs are currently blocked
        events: list[SecurityEventResponse] = []
        for row in rows:
            ip_str = str(row.ip_address)
            is_blocked = bool(await self.redis.get(self._blocked_key(ip_str)))

            # Gather targeted emails for this IP
            emails_stmt = (
                select(LoginAttempt.email)
                .where(LoginAttempt.ip_address == row.ip_address)
                .where(LoginAttempt.attempted_at >= since)
                .where(LoginAttempt.email.isnot(None))
                .distinct()
                .limit(10)
            )
            email_result = await self.session.execute(emails_stmt)
            emails = [e for (e,) in email_result.all() if e]

            events.append(
                SecurityEventResponse(
                    ip_address=ip_str,
                    failure_count=row.failure_count,
                    first_seen=row.first_seen,
                    last_seen=row.last_seen,
                    is_blocked=is_blocked,
                    emails_targeted=emails,
                )
            )
        return events


def _require_platform_admin(actor: User) -> None:
    if not actor.is_platform_admin:
        raise ForbiddenException("Platform admin access required")

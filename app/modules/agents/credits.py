"""
Call-minute credit tracking and enforcement.

Stores monthly call-minute usage in Redis with a TTL aligned to the end of
the current calendar month.  On each call completion the pipeline calls
``check_and_deduct()`` with the call duration; if the org would exceed its
monthly quota a ``ForbiddenException`` is raised.

Redis key schema
────────────────
  call_minutes:{org_id}:{YYYY-MM}   INCRBY duration_seconds
  call_minutes_ttl is set to the first second of next month.

Limit convention (mirrors seed_features_ai.py / FeatureCheckResult)
──────────────────────────────────────────────────────────────────────
  None → boolean feature carry-over — treat as unlimited
  0    → explicitly unlimited
  N>0  → capped at N minutes per month
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from typing import NamedTuple
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.modules.features.service import FeatureService

# Feature keys used by this service
_MINUTES_FEATURE = "ai.calls.minutes"


class MinutesUsage(NamedTuple):
    used_minutes: int
    allowed_minutes: int | None  # None = unlimited


def _month_key(org_id: UUID) -> str:
    ym = datetime.now(UTC).strftime("%Y-%m")
    return f"call_minutes:{org_id}:{ym}"


def _end_of_month_ttl() -> int:
    """Seconds remaining until the first second of next month (UTC)."""
    now = datetime.now(UTC)
    # Last day of current month
    last_day = calendar.monthrange(now.year, now.month)[1]
    # First second of next month
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    delta = next_month - now
    return max(int(delta.total_seconds()), 1)


class CallCreditService:
    """
    Tracks and enforces monthly AI call-minute quotas.

    Inject via FastAPI dependencies or instantiate directly in services.
    """

    def __init__(self, session: AsyncSession, redis: aioredis.Redis) -> None:
        self._session = session
        self._redis = redis
        self._feature_svc = FeatureService(session, redis)

    # ── Public API ────────────────────────────────────────────────────────

    async def get_usage(self, org_id: UUID) -> MinutesUsage:
        """
        Return (used_minutes, allowed_minutes) for the current month.

        ``allowed_minutes = None`` means the org has an unlimited quota.
        """
        allowed = await self._get_allowed(org_id)
        raw = await self._redis.get(_month_key(org_id))
        used_seconds = int(raw or 0)
        used_minutes = used_seconds // 60
        return MinutesUsage(used_minutes=used_minutes, allowed_minutes=allowed)

    async def check_and_deduct(
        self,
        org_id: UUID,
        duration_seconds: int,
    ) -> None:
        """
        Enforce the monthly limit and record usage.

        Raises ``ForbiddenException`` *before* deduction if the call would
        push the org over its quota.  Pass ``duration_seconds = 0`` to only
        record a zero-second event (e.g. for failed calls).

        Thread-safe: INCRBY is atomic in Redis.
        """
        if duration_seconds < 0:
            duration_seconds = 0

        allowed = await self._get_allowed(org_id)

        if allowed is not None and allowed > 0:
            # Check whether adding this call would exceed the cap
            raw = await self._redis.get(_month_key(org_id))
            current_seconds = int(raw or 0)
            current_minutes = current_seconds // 60
            incoming_minutes = duration_seconds // 60

            if current_minutes + incoming_minutes > allowed:
                remaining = max(0, allowed - current_minutes)
                raise ForbiddenException(
                    f"Monthly call-minute limit reached "
                    f"({allowed} min/month). "
                    f"{remaining} minute(s) remaining this month. "
                    f"Upgrade your plan to continue."
                )

        if duration_seconds > 0:
            key = _month_key(org_id)
            await self._redis.incrby(key, duration_seconds)
            # Refresh expiry so the key always lives until end-of-month
            await self._redis.expire(key, _end_of_month_ttl())

    async def reset_usage(self, org_id: UUID) -> None:
        """
        Delete the current-month counter for an org.

        Useful in tests and for admin overrides / plan upgrades.
        """
        await self._redis.delete(_month_key(org_id))

    # ── Private helpers ───────────────────────────────────────────────────

    async def _get_allowed(self, org_id: UUID) -> int | None:
        """
        Resolve the monthly minute limit for the org.

        Returns:
          None  — unlimited (no cap)
          0     — feature disabled / unlimited depending on sentinel:
                  we treat stored 0 as unlimited (seed_features_ai convention)
          N>0   — capped at N minutes per month
        """
        result = await self._feature_svc.check(org_id, _MINUTES_FEATURE)
        if not result.enabled:
            # Feature not enabled at all on this plan
            return 0  # effectively unlimited if not gated separately

        limit = result.limit  # int | None from FeatureCheckResult
        if limit is None or limit == 0:
            return None  # unlimited

        return limit  # positive integer cap

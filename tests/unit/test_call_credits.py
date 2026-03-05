"""
Unit tests for CallCreditService (Day 13).

Tests credit tracking, enforcement, and month-boundary helpers without
requiring a live Redis or database connection — all external calls are
mocked.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ── We test the pure helper functions first, then the service methods ────────

# Import target module
from app.modules.agents.credits import (
    CallCreditService,
    MinutesUsage,
    _end_of_month_ttl,
    _month_key,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_svc(redis_get_return=b"0", feature_limit: int | None = 60):
    """
    Build a CallCreditService with all I/O mocked.

    ``feature_limit`` controls what FeatureService.check() resolves to:
      None  → unlimited
      0     → unlimited
      N>0   → capped at N minutes
    """
    session = MagicMock()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=redis_get_return)
    redis.incrby = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=1)
    redis.delete = AsyncMock(return_value=1)

    from app.modules.features.schemas import FeatureCheckResult

    check_result = FeatureCheckResult(
        feature_key="ai.calls.minutes",
        enabled=feature_limit != -1,
        limit=feature_limit,
    )

    svc = CallCreditService(session, redis)
    svc._feature_svc = AsyncMock()
    svc._feature_svc.check = AsyncMock(return_value=check_result)
    svc._redis = redis
    return svc, redis


# ── _month_key ────────────────────────────────────────────────────────────────

class TestMonthKey:
    def test_contains_org_id(self):
        org_id = uuid4()
        key = _month_key(org_id)
        assert str(org_id) in key

    def test_contains_current_year_month(self):
        org_id = uuid4()
        key = _month_key(org_id)
        ym = datetime.now(UTC).strftime("%Y-%m")
        assert ym in key

    def test_prefix(self):
        org_id = uuid4()
        key = _month_key(org_id)
        assert key.startswith("call_minutes:")


# ── _end_of_month_ttl ─────────────────────────────────────────────────────────

class TestEndOfMonthTtl:
    def test_positive_and_reasonable(self):
        ttl = _end_of_month_ttl()
        assert ttl > 0
        # Can never be more than 31 days worth of seconds
        assert ttl <= 31 * 24 * 3600 + 1

    def test_december_wraps_to_january(self):
        """Mock time to December 31 and verify TTL crosses year boundary."""
        frozen = datetime(2025, 12, 31, 23, 59, 0, tzinfo=UTC)
        with patch("app.modules.agents.credits.datetime") as mock_dt:
            mock_dt.now.return_value = frozen
            ttl = _end_of_month_ttl()
        assert ttl <= 65  # <65 seconds to midnight Jan 1
        assert ttl > 0


# ── get_usage ─────────────────────────────────────────────────────────────────

class TestGetUsage:
    @pytest.mark.asyncio
    async def test_zero_usage_fresh_org(self):
        org_id = uuid4()
        svc, _ = _make_svc(redis_get_return=None, feature_limit=60)
        usage = await svc.get_usage(org_id)
        assert isinstance(usage, MinutesUsage)
        assert usage.used_minutes == 0
        assert usage.allowed_minutes == 60

    @pytest.mark.asyncio
    async def test_partial_usage_returned_in_minutes(self):
        org_id = uuid4()
        # 360 seconds = 6 minutes
        svc, _ = _make_svc(redis_get_return=b"360", feature_limit=60)
        usage = await svc.get_usage(org_id)
        assert usage.used_minutes == 6
        assert usage.allowed_minutes == 60

    @pytest.mark.asyncio
    async def test_unlimited_limit_returns_none(self):
        org_id = uuid4()
        svc, _ = _make_svc(redis_get_return=b"0", feature_limit=0)
        usage = await svc.get_usage(org_id)
        assert usage.allowed_minutes is None

    @pytest.mark.asyncio
    async def test_unlimited_when_feature_limit_none(self):
        org_id = uuid4()
        svc, _ = _make_svc(redis_get_return=b"0", feature_limit=None)
        usage = await svc.get_usage(org_id)
        assert usage.allowed_minutes is None


# ── check_and_deduct ──────────────────────────────────────────────────────────

class TestCheckAndDeduct:
    @pytest.mark.asyncio
    async def test_deducts_seconds_into_redis(self):
        org_id = uuid4()
        svc, redis = _make_svc(redis_get_return=b"0", feature_limit=60)
        await svc.check_and_deduct(org_id, duration_seconds=120)
        redis.incrby.assert_called_once()
        args = redis.incrby.call_args[0]
        assert args[1] == 120  # incremented by 120 seconds

    @pytest.mark.asyncio
    async def test_sets_expiry_after_increment(self):
        org_id = uuid4()
        svc, redis = _make_svc(redis_get_return=b"0", feature_limit=60)
        await svc.check_and_deduct(org_id, duration_seconds=30)
        redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_increment_for_zero_duration(self):
        org_id = uuid4()
        svc, redis = _make_svc(redis_get_return=b"0", feature_limit=60)
        await svc.check_and_deduct(org_id, duration_seconds=0)
        redis.incrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_when_cap_would_be_exceeded(self):
        from app.core.exceptions import ForbiddenException

        org_id = uuid4()
        # 59 minutes already used, cap is 60, incoming = 5 minutes = 300 sec
        svc, _ = _make_svc(redis_get_return=b"3540", feature_limit=60)  # 3540s = 59 min
        with pytest.raises(ForbiddenException):
            await svc.check_and_deduct(org_id, duration_seconds=300)

    @pytest.mark.asyncio
    async def test_no_raise_at_exactly_limit(self):
        """Using the last available minute should NOT raise."""
        org_id = uuid4()
        # 59 minutes used, cap 60, incoming 1 minute → total = 60 (exactly at cap)
        svc, redis = _make_svc(redis_get_return=b"3540", feature_limit=60)
        await svc.check_and_deduct(org_id, duration_seconds=60)
        redis.incrby.assert_called_once()

    @pytest.mark.asyncio
    async def test_unlimited_feature_never_raises(self):
        org_id = uuid4()
        # Feature limit = 0 → unlimited; pretend 10 000 minutes used
        svc, redis = _make_svc(redis_get_return=b"600000", feature_limit=0)
        # Should not raise even for a very long call
        await svc.check_and_deduct(org_id, duration_seconds=99999)
        redis.incrby.assert_called_once()

    @pytest.mark.asyncio
    async def test_negative_duration_normalised_to_zero(self):
        org_id = uuid4()
        svc, redis = _make_svc(redis_get_return=b"0", feature_limit=60)
        await svc.check_and_deduct(org_id, duration_seconds=-50)
        redis.incrby.assert_not_called()


# ── reset_usage ───────────────────────────────────────────────────────────────

class TestResetUsage:
    @pytest.mark.asyncio
    async def test_deletes_redis_key(self):
        org_id = uuid4()
        svc, redis = _make_svc()
        await svc.reset_usage(org_id)
        redis.delete.assert_called_once()
        key_arg = redis.delete.call_args[0][0]
        assert str(org_id) in key_arg

    @pytest.mark.asyncio
    async def test_usage_is_zero_after_reset(self):
        org_id = uuid4()
        svc, redis = _make_svc(redis_get_return=b"3600", feature_limit=60)
        # After reset, simulate redis returning None (key deleted)
        redis.get = AsyncMock(return_value=None)
        await svc.reset_usage(org_id)
        usage = await svc.get_usage(org_id)
        assert usage.used_minutes == 0

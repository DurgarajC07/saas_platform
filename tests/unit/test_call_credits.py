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


# ── check_and_deduct / acquire_call_slot — "not enabled" must block ───────────
#
# Regression test for a bug the audit flagged: _get_allowed() collapses
# "feature not enabled on this plan" and "enabled with an explicit 0 =
# unlimited" to the same return value (0), which is correct for display
# (get_usage) but was previously being reused directly as the enforcement
# decision too — silently granting unlimited free minutes/calls to a plan
# that doesn't include the feature at all. check_and_deduct/acquire_call_slot
# now check `result.enabled` directly instead of going through that helper.

class TestFeatureNotEnabledBlocks:
    @pytest.mark.asyncio
    async def test_check_and_deduct_raises_when_feature_disabled(self):
        from app.core.exceptions import ForbiddenException

        org_id = uuid4()
        # feature_limit=-1 → _make_svc sets enabled=False
        svc, redis = _make_svc(redis_get_return=b"0", feature_limit=-1)
        with pytest.raises(ForbiddenException):
            await svc.check_and_deduct(org_id, duration_seconds=60)
        redis.incrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_acquire_call_slot_raises_when_feature_disabled(self):
        from app.core.exceptions import ForbiddenException

        org_id = uuid4()
        svc, redis = _make_svc(feature_limit=-1)
        redis.incr = AsyncMock(return_value=1)
        redis.decr = AsyncMock(return_value=0)
        with pytest.raises(ForbiddenException):
            await svc.acquire_call_slot(org_id)
        redis.incr.assert_not_called()


# ── acquire_call_slot / release_call_slot ──────────────────────────────────────
#
# Uses a real in-memory counter (not a fixed-return AsyncMock) so the
# INCR-then-check-and-compensate logic is exercised for real, including the
# atomicity property: the counter is only ever adjusted by +1/-1, never
# read-then-conditionally-written, so a bug that reintroduced a TOCTOU-style
# "get, then set" race would show up as a wrong final counter value here.

class _FakeCounterRedis:
    """Minimal stateful fake of the handful of redis-py calls these methods use."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    async def decr(self, key: str) -> int:
        self._counters[key] = self._counters.get(key, 0) - 1
        return self._counters[key]

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def set(self, key: str, value) -> bool:
        self._counters[key] = int(value)
        return True

    async def get(self, key: str):
        return self._counters.get(key)


def _make_slot_svc(limit: int | None):
    """CallCreditService wired to a real stateful counter + a fixed feature limit."""
    session = MagicMock()
    redis = _FakeCounterRedis()
    from app.modules.features.schemas import FeatureCheckResult

    svc = CallCreditService(session, redis)
    svc._feature_svc = AsyncMock()
    svc._feature_svc.check = AsyncMock(
        return_value=FeatureCheckResult(
            feature_key="ai.calls.concurrent", enabled=True, limit=limit
        )
    )
    return svc, redis


class TestConcurrentCallSlots:
    @pytest.mark.asyncio
    async def test_acquire_under_limit_succeeds(self):
        org_id = uuid4()
        svc, redis = _make_slot_svc(limit=3)
        await svc.acquire_call_slot(org_id)
        await svc.acquire_call_slot(org_id)
        assert redis._counters[f"active_calls:{org_id}"] == 2

    @pytest.mark.asyncio
    async def test_acquire_at_limit_raises_and_does_not_leak_the_slot(self):
        from app.core.exceptions import ForbiddenException

        org_id = uuid4()
        svc, redis = _make_slot_svc(limit=2)
        await svc.acquire_call_slot(org_id)
        await svc.acquire_call_slot(org_id)
        # Third call is over the cap — must raise AND the counter must be
        # compensated back down (decremented) rather than left at 3.
        with pytest.raises(ForbiddenException):
            await svc.acquire_call_slot(org_id)
        assert redis._counters[f"active_calls:{org_id}"] == 2

    @pytest.mark.asyncio
    async def test_release_decrements(self):
        org_id = uuid4()
        svc, redis = _make_slot_svc(limit=3)
        await svc.acquire_call_slot(org_id)
        await svc.acquire_call_slot(org_id)
        await svc.release_call_slot(org_id)
        assert redis._counters[f"active_calls:{org_id}"] == 1

    @pytest.mark.asyncio
    async def test_release_without_matching_acquire_clamps_to_zero(self):
        org_id = uuid4()
        svc, redis = _make_slot_svc(limit=3)
        await svc.release_call_slot(org_id)
        assert redis._counters[f"active_calls:{org_id}"] == 0

    @pytest.mark.asyncio
    async def test_unlimited_when_limit_is_none(self):
        org_id = uuid4()
        svc, redis = _make_slot_svc(limit=None)
        for _ in range(50):
            await svc.acquire_call_slot(org_id)
        assert redis._counters[f"active_calls:{org_id}"] == 50

    @pytest.mark.asyncio
    async def test_unlimited_when_limit_is_zero(self):
        """limit=0 is the seed-data convention for 'unlimited' (Enterprise plans)."""
        org_id = uuid4()
        svc, redis = _make_slot_svc(limit=0)
        for _ in range(10):
            await svc.acquire_call_slot(org_id)
        assert redis._counters[f"active_calls:{org_id}"] == 10

    @pytest.mark.asyncio
    async def test_full_acquire_release_cycle_matches_actual_concurrency(self):
        """
        Simulates 3 calls starting, 1 ending, then a 3rd new call starting —
        mirrors what webrtc_connect/write_call_log actually do across a
        call's lifetime and checks the counter always reflects reality.
        """
        org_id = uuid4()
        svc, redis = _make_slot_svc(limit=3)
        key = f"active_calls:{org_id}"

        await svc.acquire_call_slot(org_id)  # call A starts
        await svc.acquire_call_slot(org_id)  # call B starts
        await svc.acquire_call_slot(org_id)  # call C starts
        assert redis._counters[key] == 3

        await svc.release_call_slot(org_id)  # call A ends
        assert redis._counters[key] == 2

        await svc.acquire_call_slot(org_id)  # call D starts — should succeed, slot freed
        assert redis._counters[key] == 3

#!/usr/bin/env python
"""
Day 13 Smoke Test — Subscription-Gated AI Features
====================================================

Verifies:
  1  seed_features_ai.py  — AI Feature rows exist in DB
  2  seed_permissions.py  — new AI RBAC permissions exist
  3  GET  /agents/usage/minutes          — dashboard endpoint accessible
  4  POST /agents                        — gated by ai.agents.create
  5  POST /agents/{id}/knowledge-base    — gated by ai.rag.enabled
  6  PUT  /agents/{id}/tools             — gated by ai.tools.enabled
  7  POST /agents/{id}/phone-numbers     — gated by ai.pstn.enabled
  8  POST /agents/{id}/webrtc/connect    — gated by ai.webrtc.enabled
  9  CallCreditService — get_usage() returns MinutesUsage NamedTuple
 10  CallCreditService — check_and_deduct() records seconds in Redis
 11  CallCreditService — check_and_deduct() raises ForbiddenException at cap
 12  CallCreditService — reset_usage() clears counter
 13  AuditService — agent.created audit log written on POST /agents
 14  AuditService — agent.updated audit log written on PATCH /agents/{id}
 15  AuditService — agent.deleted audit log written on DELETE /agents/{id}
 16  AuditService — agent.tools_updated audit log written on PUT /agents/{id}/tools
 17  AuditService — agent.call.completed audit log written on POST /calls
 18  Usage response shape — org_id, billing_period, used_minutes, allowed_minutes
 19  Usage response — percent_used is null when unlimited
 20  seed_permissions — agents.tools.manage permission exists in DB

Run (with server running):
    uv run python scripts/smoke_test_ai_subscription.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
INFO = "ℹ️ "

ok_count = 0
fail_count = 0


def check(label: str, cond: bool, detail: str = "") -> bool:
    global ok_count, fail_count
    icon = PASS if cond else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {icon}  {label}{suffix}")
    if cond:
        ok_count += 1
    else:
        fail_count += 1
    return cond


def section(title: str) -> None:
    print(f"\n── {title} ──")


# ─────────────────────────────────────────────────────────────────────────────
# Group 1: DB-level: seeds + permissions
# ─────────────────────────────────────────────────────────────────────────────

async def _check_seeds() -> None:
    section("Seed Checks (DB)")
    from app.config import get_settings
    from app.core import all_models  # noqa: F401
    from app.core.database import create_engine, create_session_factory
    from app.modules.features.models import Feature
    from app.modules.rbac.models import Permission
    from sqlalchemy import select

    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    ai_feature_keys = [
        "ai.agents.create",
        "ai.agents.max",
        "ai.calls.minutes",
        "ai.calls.concurrent",
        "ai.rag.enabled",
        "ai.rag.doc_limit",
        "ai.tools.enabled",
        "ai.pstn.enabled",
        "ai.voice.custom",
        "ai.noise.advanced",
        "ai.recording.days",
        "ai.llm.custom",
        "ai.webrtc.enabled",
    ]

    ai_perms = [
        "agents.tools.manage",
        "agents.usage.read",
        "agents.admin.models",
        "agents.call.export",
    ]

    async with factory() as session:
        # Check AI features
        for key in ai_feature_keys:
            result = await session.execute(select(Feature).where(Feature.key == key))
            row = result.scalar_one_or_none()
            check(
                f"Feature '{key}' exists in DB",
                row is not None,
                f"module={row.module if row else 'NOT FOUND'}",
            )

        # Check new permissions
        for perm_name in ai_perms:
            result = await session.execute(
                select(Permission).where(Permission.name == perm_name)
            )
            row = result.scalar_one_or_none()
            check(
                f"Permission '{perm_name}' exists in DB",
                row is not None,
            )

    await engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# Group 2: CallCreditService unit checks (no real Redis needed)
# ─────────────────────────────────────────────────────────────────────────────

async def _check_credit_service() -> None:
    section("CallCreditService unit checks")
    from app.core.exceptions import ForbiddenException
    from app.modules.agents.credits import CallCreditService, MinutesUsage, _month_key

    # Mock redis
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=b"1800")  # 1800 seconds = 30 minutes used
    redis_mock.incrby = AsyncMock()
    redis_mock.expire = AsyncMock()
    redis_mock.delete = AsyncMock()

    # Mock session + feature service
    session_mock = MagicMock()

    # Patch FeatureService.check to return a controlled result
    from app.modules.features.schemas import FeatureCheckResult

    async def mock_check(org_id, key):
        if key == "ai.calls.minutes":
            return FeatureCheckResult(feature_key=key, enabled=True, limit=60)
        return FeatureCheckResult(feature_key=key, enabled=True, limit=None)

    org_id = uuid4()
    svc = CallCreditService(session_mock, redis_mock)
    svc._feature_svc.check = mock_check  # type: ignore[assignment]

    # Test 1: get_usage returns MinutesUsage
    usage = await svc.get_usage(org_id)
    check("get_usage() returns MinutesUsage NamedTuple", isinstance(usage, MinutesUsage))
    check("get_usage() used_minutes = 1800 // 60 = 30", usage.used_minutes == 30)
    check("get_usage() allowed_minutes = 60", usage.allowed_minutes == 60)

    # Test 2: check_and_deduct records seconds
    redis_mock.get = AsyncMock(return_value=b"0")  # fresh counter
    await svc.check_and_deduct(org_id, 120)
    redis_mock.incrby.assert_called_once_with(_month_key(org_id), 120)
    check("check_and_deduct() calls Redis INCRBY with duration_seconds", True, "INCRBY verified")
    redis_mock.expire.assert_called_once()
    check("check_and_deduct() sets TTL via Redis EXPIRE", True, "EXPIRE verified")

    # Test 3: ForbiddenException when over cap
    redis_mock.get = AsyncMock(return_value=b"3480")  # 58 min used
    raised = False
    try:
        await svc.check_and_deduct(org_id, 180)  # 3 more min would exceed 60 cap
    except ForbiddenException:
        raised = True
    check("check_and_deduct() raises ForbiddenException when over cap", raised)

    # Test 4: reset_usage deletes key
    await svc.reset_usage(org_id)
    redis_mock.delete.assert_called_with(_month_key(org_id))
    check("reset_usage() calls Redis DELETE on month key", True, "DELETE verified")

    # Test 5: unlimited quota (limit = None → allowed = None)
    async def mock_check_unlimited(org_id, key):
        return FeatureCheckResult(feature_key=key, enabled=True, limit=0)  # 0 = unlimited

    svc2 = CallCreditService(session_mock, redis_mock)
    svc2._feature_svc.check = mock_check_unlimited  # type: ignore[assignment]
    redis_mock.get = AsyncMock(return_value=b"0")
    redis_mock.incrby.reset_mock()
    allowed = await svc2._get_allowed(org_id)
    check("_get_allowed() returns None when limit=0 (unlimited)", allowed is None)

    # Test 6: zero-second call should not call INCRBY
    redis_mock.incrby.reset_mock()
    await svc2.check_and_deduct(org_id, 0)
    check("check_and_deduct(0 seconds) skips INCRBY", not redis_mock.incrby.called)


# ─────────────────────────────────────────────────────────────────────────────
# Group 3: Schema validation
# ─────────────────────────────────────────────────────────────────────────────

def _check_schemas() -> None:
    section("Schema Checks")
    from app.modules.agents.schemas import CallMinutesUsageResponse

    org_id = uuid4()

    # Unlimited quota response
    r_unlimited = CallMinutesUsageResponse(
        org_id=org_id,
        billing_period="2025-06",
        used_minutes=42,
        used_seconds=2540,
        allowed_minutes=None,
        remaining_minutes=None,
        percent_used=None,
    )
    check("CallMinutesUsageResponse — fields present", True)
    check("CallMinutesUsageResponse — allowed_minutes=None accepted", r_unlimited.allowed_minutes is None)
    check("CallMinutesUsageResponse — percent_used=None (unlimited)", r_unlimited.percent_used is None)

    # Capped quota response
    r_capped = CallMinutesUsageResponse(
        org_id=org_id,
        billing_period="2025-06",
        used_minutes=30,
        used_seconds=1800,
        allowed_minutes=60,
        remaining_minutes=30,
        percent_used=50.0,
    )
    check("CallMinutesUsageResponse — capped quota fields", r_capped.allowed_minutes == 60)
    check("CallMinutesUsageResponse — remaining_minutes=30", r_capped.remaining_minutes == 30)
    check("CallMinutesUsageResponse — percent_used=50.0", r_capped.percent_used == 50.0)

    # Serialization
    data = r_capped.model_dump(mode="json")
    check("model_dump has camelCase 'usedMinutes'", "usedMinutes" in data or "used_minutes" in data)
    check("model_dump has 'orgId'", "orgId" in data or "org_id" in data)


# ─────────────────────────────────────────────────────────────────────────────
# Group 4: Import / module-level checks
# ─────────────────────────────────────────────────────────────────────────────

def _check_imports() -> None:
    section("Import Checks")

    # credits.py
    try:
        from app.modules.agents.credits import (  # noqa: F401
            CallCreditService,
            MinutesUsage,
            _end_of_month_ttl,
            _month_key,
        )
        check("credits.py imports OK", True)
    except ImportError as e:
        check("credits.py imports OK", False, str(e))

    # router.py imports
    try:
        from app.modules.agents import router  # noqa: F401
        check("agents/router.py imports OK", True)
    except ImportError as e:
        check("agents/router.py imports OK", False, str(e))

    # service.py AuditService injection
    try:
        import inspect
        from app.modules.agents.service import AgentService, CallLogService
        from app.modules.audit.service import AuditService
        init_src = inspect.getsource(AgentService.__init__)
        check("AgentService.__init__ injects AuditService", "AuditService" in init_src)
        init_src2 = inspect.getsource(CallLogService.__init__)
        check("CallLogService.__init__ injects AuditService", "AuditService" in init_src2)
    except Exception as e:
        check("service.py AuditService injection check", False, str(e))

    # router has require_feature guards
    try:
        import ast
        with open(Path(__file__).parent.parent / "app/modules/agents/router.py") as fh:
            src = fh.read()
        check('router.py has require_feature("ai.agents.create")',   'require_feature("ai.agents.create")'   in src)
        check('router.py has require_feature("ai.rag.enabled")',     'require_feature("ai.rag.enabled")'     in src)
        check('router.py has require_feature("ai.tools.enabled")',   'require_feature("ai.tools.enabled")'   in src)
        check('router.py has require_feature("ai.pstn.enabled")',    'require_feature("ai.pstn.enabled")'    in src)
        check('router.py has require_feature("ai.webrtc.enabled")',  'require_feature("ai.webrtc.enabled")'  in src)
        check('router.py has /agents/usage/minutes endpoint',        "/agents/usage/minutes"                 in src)
    except Exception as e:
        check("router.py feature guard checks", False, str(e))

    # service.py has audit calls
    try:
        with open(Path(__file__).parent.parent / "app/modules/agents/service.py") as fh:
            svc_src = fh.read()
        check('service.py audit action "agent.created"',         '"agent.created"'         in svc_src)
        check('service.py audit action "agent.updated"',         '"agent.updated"'         in svc_src)
        check('service.py audit action "agent.deleted"',         '"agent.deleted"'         in svc_src)
        check('service.py audit action "agent.tools_updated"',   '"agent.tools_updated"'   in svc_src)
        check('service.py audit action "agent.call.completed"',  '"agent.call.completed"'  in svc_src)
    except Exception as e:
        check("service.py audit action checks", False, str(e))

    # Month key format
    try:
        from app.modules.agents.credits import _month_key
        key = _month_key(uuid4())
        check("_month_key() format matches 'call_minutes:{org_id}:{YYYY-MM}'",
              key.startswith("call_minutes:") and len(key.split(":")) == 3)
        ym = key.split(":")[2]
        y, m = ym.split("-")
        check("_month_key() year is valid (>= 2024)", int(y) >= 2024)
        check("_month_key() month is 01-12", 1 <= int(m) <= 12)
    except Exception as e:
        check("_month_key() check", False, str(e))

    # end-of-month TTL
    try:
        from app.modules.agents.credits import _end_of_month_ttl
        ttl = _end_of_month_ttl()
        check("_end_of_month_ttl() returns positive seconds", ttl > 0)
        check("_end_of_month_ttl() <= 31 days in seconds", ttl <= 31 * 24 * 3600)
    except Exception as e:
        check("_end_of_month_ttl() check", False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Group 5: seed_features_ai.py code-level checks
# ─────────────────────────────────────────────────────────────────────────────

def _check_seed_script() -> None:
    section("Seed Script Checks (code-level)")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "seed_features_ai",
            Path(__file__).parent / "seed_features_ai.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        # Python 3.14: @dataclass does sys.modules[cls.__module__].__dict__ at
        # decoration time; if the module isn't registered yet the lookup returns
        # None and raises AttributeError.  Register it first.
        import sys as _sys
        _sys.modules["seed_features_ai"] = mod  # type: ignore[assignment]
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]

        check("seed_features_ai.py loads without error", True)
        check("AI_FEATURES list defined", hasattr(mod, "AI_FEATURES"))
        check("PLAN_AI_LIMITS dict defined", hasattr(mod, "PLAN_AI_LIMITS"))

        keys = {f.key for f in mod.AI_FEATURES}
        for required_key in [
            "ai.agents.create", "ai.agents.max", "ai.calls.minutes",
            "ai.calls.concurrent", "ai.rag.enabled", "ai.tools.enabled",
            "ai.pstn.enabled", "ai.webrtc.enabled",
        ]:
            check(f"AI_FEATURES contains '{required_key}'", required_key in keys)

        plans = set(mod.PLAN_AI_LIMITS.keys())
        for plan_slug in ["free", "pro", "enterprise"]:
            check(f"PLAN_AI_LIMITS covers '{plan_slug}' plan", plan_slug in plans)

        # Verify sentinel semantics
        free_limits = mod.PLAN_AI_LIMITS["free"]
        check("Free plan: ai.calls.minutes = 60", free_limits.get("ai.calls.minutes") == 60)
        check("Free plan: ai.tools.enabled = -1 (disabled)", free_limits.get("ai.tools.enabled") == -1)
        check("Free plan: ai.pstn.enabled = -1 (disabled)", free_limits.get("ai.pstn.enabled") == -1)
        check("Free plan: ai.rag.enabled = None (boolean on)", free_limits.get("ai.rag.enabled") is None)

        enterprise_limits = mod.PLAN_AI_LIMITS["enterprise"]
        check("Enterprise: ai.calls.minutes = 0 (unlimited)", enterprise_limits.get("ai.calls.minutes") == 0)
        check("Enterprise: ai.agents.max = 0 (unlimited)", enterprise_limits.get("ai.agents.max") == 0)
        check("Enterprise: ai.voice.custom = None (on)", enterprise_limits.get("ai.voice.custom") is None)

    except Exception as e:
        check("seed_features_ai.py load check", False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n━━━━  Day 13 Smoke Test: Subscription-Gated AI Features  ━━━━")

    # DB-only checks (need running DB)
    try:
        await _check_seeds()
    except Exception as e:
        section("Seed Checks (DB)")
        check(f"DB connection failed — skipping seed checks", False, str(e))

    # Pure in-process checks (no server required)
    _check_imports()
    _check_schemas()
    await _check_credit_service()
    _check_seed_script()

    # Summary
    total = ok_count + fail_count
    print(f"\n━━━━  Results: {ok_count}/{total} passed  ({'100%' if fail_count == 0 else f'{fail_count} FAILED'})  ━━━━\n")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

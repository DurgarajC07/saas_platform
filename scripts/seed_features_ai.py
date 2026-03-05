#!/usr/bin/env python
"""
Seed AI-module feature flags and their per-plan limits.

Creates/updates Feature rows (module='ai_calls') and PlanFeature rows for
the Free, Pro, and Enterprise plans.

Feature limit sentinels (same convention as seed_plans.py):
  NULL (None)  — boolean feature, enabled
  -1           — feature disabled for this plan
  0            — unlimited / no numeric cap
  int > 0      — capped at that value

Usage:
    uv run python scripts/seed_features_ai.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import all_models  # noqa: F401 — populate mapper registry
from app.core.database import create_engine, create_session_factory
from app.modules.billing.models import SubscriptionPlan
from app.modules.features.models import Feature, PlanFeature

# ── AI Feature definitions ─────────────────────────────────────────────────

@dataclass
class AIFeatureDef:
    key: str
    name: str
    description: str
    module: str = "ai_calls"


AI_FEATURES: list[AIFeatureDef] = [
    # Agent CRUD capability
    AIFeatureDef("ai.agents.create",       "AI Agents — Create",              "Ability to create AI voice agents"),
    AIFeatureDef("ai.agents.max",          "AI Agents — Max Count",           "Maximum number of AI agents per org"),
    # Call quotas
    AIFeatureDef("ai.calls.minutes",       "AI Calls — Monthly Minutes",      "Monthly allotment of AI call-minutes (0 = unlimited)"),
    AIFeatureDef("ai.calls.concurrent",    "AI Calls — Concurrent Calls",     "Maximum simultaneous active calls"),
    # RAG knowledge base
    AIFeatureDef("ai.rag.enabled",         "AI RAG — Knowledge Base",         "Upload documents and use retrieval-augmented generation"),
    AIFeatureDef("ai.rag.doc_limit",       "AI RAG — Document Limit",         "Maximum KB documents per org (0 = unlimited)"),
    # Function calling / tools
    AIFeatureDef("ai.tools.enabled",       "AI Tools — Function Calling",     "Enable custom tool / function-calling definitions"),
    # PSTN telephony
    AIFeatureDef("ai.pstn.enabled",        "AI PSTN — Telephony",             "Assign real phone numbers and receive inbound PSTN calls"),
    # Voice & audio
    AIFeatureDef("ai.voice.custom",        "AI Voice — Custom Cloning",       "Upload custom voice clones for agents"),
    AIFeatureDef("ai.noise.advanced",      "AI Audio — Advanced Noise Cancel","Enterprise-grade noise cancellation pipeline"),
    # Recordings
    AIFeatureDef("ai.recording.days",      "AI Recording — Retention Days",   "How many days call recordings are retained (0 = unlimited)"),
    # LLM configuration
    AIFeatureDef("ai.llm.custom",          "AI LLM — Custom Model Config",    "Override the default LLM model and parameters"),
    # WebRTC browser calling
    AIFeatureDef("ai.webrtc.enabled",      "AI WebRTC — Browser Calling",     "WebRTC browser-to-agent calling via ai-call-sdk"),
]

# ── Per-plan limits ────────────────────────────────────────────────────────
# Format:  { feature_key: limit_value }
#   None  → boolean on
#   -1    → disabled for this plan
#   0     → unlimited
#   N>0   → capped at N

PLAN_AI_LIMITS: dict[str, dict[str, int | None]] = {
    "free": {
        "ai.agents.create":    None,   # can create agents
        "ai.agents.max":       1,      # max 1 agent
        "ai.calls.minutes":    60,     # 60 min/month
        "ai.calls.concurrent": 1,      # 1 concurrent call
        "ai.rag.enabled":      None,   # RAG on
        "ai.rag.doc_limit":    5,      # 5 documents
        "ai.tools.enabled":    -1,     # tools disabled
        "ai.pstn.enabled":     -1,     # PSTN disabled
        "ai.voice.custom":     -1,     # custom voice disabled
        "ai.noise.advanced":   -1,     # advanced noise cancel disabled
        "ai.recording.days":   7,      # 7 day retention
        "ai.llm.custom":       -1,     # custom LLM disabled
        "ai.webrtc.enabled":   None,   # WebRTC on (browser demo)
    },
    "pro": {
        "ai.agents.create":    None,
        "ai.agents.max":       10,
        "ai.calls.minutes":    1000,
        "ai.calls.concurrent": 3,
        "ai.rag.enabled":      None,
        "ai.rag.doc_limit":    100,
        "ai.tools.enabled":    None,   # tools on
        "ai.pstn.enabled":     None,   # PSTN on
        "ai.voice.custom":     -1,     # still disabled on Pro
        "ai.noise.advanced":   None,   # advanced noise on
        "ai.recording.days":   90,
        "ai.llm.custom":       None,   # custom LLM on
        "ai.webrtc.enabled":   None,
    },
    "enterprise": {
        "ai.agents.create":    None,
        "ai.agents.max":       0,      # unlimited
        "ai.calls.minutes":    0,      # unlimited
        "ai.calls.concurrent": 5,
        "ai.rag.enabled":      None,
        "ai.rag.doc_limit":    0,      # unlimited
        "ai.tools.enabled":    None,
        "ai.pstn.enabled":     None,
        "ai.voice.custom":     None,   # custom voice on
        "ai.noise.advanced":   None,
        "ai.recording.days":   0,      # unlimited retention
        "ai.llm.custom":       None,
        "ai.webrtc.enabled":   None,
    },
}


# ── Seed helpers ──────────────────────────────────────────────────────────

async def seed_ai_features(session: AsyncSession) -> dict[str, UUID]:
    """Upsert AI Feature rows. Returns mapping key → id."""
    now = datetime.now(UTC)
    feature_ids: dict[str, UUID] = {}

    for fdef in AI_FEATURES:
        existing = await session.execute(
            select(Feature).where(Feature.key == fdef.key)
        )
        feature = existing.scalar_one_or_none()

        if feature is None:
            feature = Feature(
                id=uuid4(),
                key=fdef.key,
                name=fdef.name,
                description=fdef.description,
                module=fdef.module,
                created_at=now,
                updated_at=now,
            )
            session.add(feature)
            await session.flush()
            print(f"  [feature] CREATED  {fdef.key!r}")
        else:
            feature.name = fdef.name
            feature.description = fdef.description
            feature.module = fdef.module
            feature.updated_at = now
            print(f"  [feature] EXISTS   {fdef.key!r} (updated)")

        feature_ids[fdef.key] = feature.id

    await session.commit()
    return feature_ids


async def seed_ai_plan_features(
    session: AsyncSession,
    feature_ids: dict[str, UUID],
) -> None:
    """Upsert PlanFeature rows for AI features on each plan."""
    now = datetime.now(UTC)

    for plan_slug, limits in PLAN_AI_LIMITS.items():
        result = await session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.slug == plan_slug)
        )
        plan = result.scalar_one_or_none()

        if plan is None:
            print(f"  [plan] NOT FOUND: {plan_slug!r} — run seed_plans.py first")
            continue

        print(f"\n  [plan] {plan_slug!r}:")
        for key, limit in limits.items():
            fid = feature_ids.get(key)
            if not fid:
                print(f"    WARNING: feature key {key!r} not found, skipping.")
                continue

            existing_pf = await session.execute(
                select(PlanFeature).where(
                    PlanFeature.plan_id == plan.id,
                    PlanFeature.feature_id == fid,
                )
            )
            pf_row = existing_pf.scalar_one_or_none()

            if limit == -1:
                # Remove row to disable the feature for this plan
                if pf_row:
                    await session.delete(pf_row)
                    print(f"    [-] DISABLED  {key}")
                else:
                    print(f"    [-] ABSENT    {key} (disabled, nothing to delete)")
                continue

            if pf_row:
                pf_row.limit_value = limit
                pf_row.updated_at = now
                cap = "unlimited" if limit == 0 else ("on" if limit is None else str(limit))
                print(f"    [~] UPDATED   {key!r} → {cap}")
            else:
                pf = PlanFeature(
                    plan_id=plan.id,
                    feature_id=fid,
                    limit_value=limit,
                    created_at=now,
                    updated_at=now,
                )
                session.add(pf)
                cap = "unlimited" if limit == 0 else ("on" if limit is None else str(limit))
                print(f"    [+] CREATED   {key!r} → {cap}")

    await session.commit()
    print("\nAI plan-features seeded successfully.")


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async with factory() as session:
        print("Seeding AI feature definitions...")
        feature_ids = await seed_ai_features(session)
        print("\nSeeding AI plan-feature limits...")
        await seed_ai_plan_features(session, feature_ids)

    await engine.dispose()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python
"""
Seed subscription plans, features, and plan-feature links.

Creates:
  Plans  : Free, Pro, Enterprise
  Features: sso, api_access, advanced_analytics, custom_domain,
            priority_support, audit_logs, file_storage, webhooks, seats
  PlanFeatures: join rows with optional numeric limit_value

Usage:
    uv run python scripts/seed_plans.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from datetime import datetime, UTC
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import all_models  # noqa: F401 — populate SQLAlchemy mapper registry
from app.core.database import create_engine, create_session_factory
from app.modules.billing.models import SubscriptionPlan
from app.modules.features.models import Feature, PlanFeature


# ── Feature definitions ───────────────────────────────────────────────────
# Feature.key is the unique identifier, Feature.module groups them.

@dataclass
class FeatureDef:
    key: str
    name: str
    description: str
    module: str = "features"


FEATURES: list[FeatureDef] = [
    FeatureDef("sso",                 "Single Sign-On",        "SAML/OIDC SSO integration"),
    FeatureDef("api_access",          "API Access",            "Programmatic REST API access"),
    FeatureDef("advanced_analytics",  "Advanced Analytics",    "Extended reporting and analytics dashboards"),
    FeatureDef("custom_domain",       "Custom Domain",         "Custom subdomain for your workspace"),
    FeatureDef("priority_support",    "Priority Support",      "Dedicated support with SLA guarantees"),
    FeatureDef("audit_logs",          "Audit Logs",            "Full immutable audit trail"),
    FeatureDef("file_storage",        "File Storage",          "Attached file storage capacity (MB)", module="files"),
    FeatureDef("webhooks",            "Webhooks",              "Outbound webhook delivery"),
    FeatureDef("seats",               "Team Seats",            "Maximum members per organization",     module="tenancy"),
]


# ── Plan definitions ──────────────────────────────────────────────────────
# PlanFeature only stores: plan_id, feature_id, limit_value (int|None).
# NULL limit = boolean feature (on/off).
# Negative sentinel (-1) = feature disabled for this plan.
# Positive int = feature enabled with that numeric cap.
# 0 = unlimited / no cap.

@dataclass
class PlanDef:
    slug: str
    name: str
    description: str
    price_monthly: Decimal
    price_yearly: Decimal
    currency: str
    trial_days: int
    max_seats: int | None
    max_storage_mb: int | None
    display_order: int
    # feature_key → limit_value (None=boolean-on, -1=disabled, int≥0=capped)
    feature_limits: dict[str, int | None]
    # Stored in SubscriptionPlan.features JSONB for quick API reads
    features_summary: dict


PLANS: list[PlanDef] = [
    PlanDef(
        slug="free",
        name="Free",
        description="Get started with core features — no credit card required.",
        price_monthly=Decimal("0.00"),
        price_yearly=Decimal("0.00"),
        currency="USD",
        trial_days=0,
        max_seats=3,
        max_storage_mb=100,
        display_order=10,
        feature_limits={
            "api_access":         None,   # boolean on
            "audit_logs":         -1,     # disabled
            "sso":                -1,
            "custom_domain":      -1,
            "advanced_analytics": -1,
            "priority_support":   -1,
            "webhooks":           -1,
            "file_storage":       100,    # 100 MB
            "seats":              3,
        },
        features_summary={
            "api_access": True, "audit_logs": False, "sso": False,
            "custom_domain": False, "advanced_analytics": False,
            "priority_support": False, "webhooks": False,
            "file_storage_mb": 100, "max_seats": 3,
        },
    ),
    PlanDef(
        slug="pro",
        name="Pro",
        description="Everything you need for a growing team.",
        price_monthly=Decimal("29.00"),
        price_yearly=Decimal("290.00"),
        currency="USD",
        trial_days=14,
        max_seats=25,
        max_storage_mb=10_240,
        display_order=20,
        feature_limits={
            "api_access":         None,
            "audit_logs":         None,
            "sso":                -1,
            "custom_domain":      None,
            "advanced_analytics": None,
            "priority_support":   -1,
            "webhooks":           10,
            "file_storage":       10_240,
            "seats":              25,
        },
        features_summary={
            "api_access": True, "audit_logs": True, "sso": False,
            "custom_domain": True, "advanced_analytics": True,
            "priority_support": False, "webhooks": 10,
            "file_storage_mb": 10240, "max_seats": 25,
        },
    ),
    PlanDef(
        slug="enterprise",
        name="Enterprise",
        description="Unlimited scale with dedicated support and compliance tools.",
        price_monthly=Decimal("299.00"),
        price_yearly=Decimal("2990.00"),
        currency="USD",
        trial_days=30,
        max_seats=None,
        max_storage_mb=204_800,
        display_order=30,
        feature_limits={
            "api_access":         None,
            "audit_logs":         None,
            "sso":                None,
            "custom_domain":      None,
            "advanced_analytics": None,
            "priority_support":   None,
            "webhooks":           0,    # 0 = unlimited
            "file_storage":       204_800,
            "seats":              0,    # unlimited
        },
        features_summary={
            "api_access": True, "audit_logs": True, "sso": True,
            "custom_domain": True, "advanced_analytics": True,
            "priority_support": True, "webhooks": "unlimited",
            "file_storage_mb": 204800, "max_seats": "unlimited",
        },
    ),
]


# ── Seeding logic ─────────────────────────────────────────────────────────

async def seed_features(session: AsyncSession) -> dict[str, UUID]:
    """Upsert Feature rows; return {key: id} map."""
    now = datetime.now(UTC)
    feature_ids: dict[str, UUID] = {}

    for fdef in FEATURES:
        existing = await session.execute(
            select(Feature).where(Feature.key == fdef.key)
        )
        row = existing.scalar_one_or_none()
        if row:
            feature_ids[fdef.key] = row.id
            print(f"  [feature] EXISTS  {fdef.key}")
            continue

        feat = Feature(
            id=uuid4(),
            key=fdef.key,
            name=fdef.name,
            description=fdef.description,
            module=fdef.module,
            created_at=now,
            updated_at=now,
        )
        session.add(feat)
        feature_ids[fdef.key] = feat.id
        print(f"  [feature] CREATED {fdef.key}")

    await session.flush()
    return feature_ids


async def seed_plans(
    session: AsyncSession,
    feature_ids: dict[str, UUID],
) -> None:
    now = datetime.now(UTC)

    for pdef in PLANS:
        existing = await session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.slug == pdef.slug)
        )
        plan = existing.scalar_one_or_none()

        if plan is None:
            plan = SubscriptionPlan(
                id=uuid4(),
                slug=pdef.slug,
                name=pdef.name,
                description=pdef.description,
                price_monthly=pdef.price_monthly,
                price_yearly=pdef.price_yearly,
                currency=pdef.currency,
                trial_days=pdef.trial_days,
                max_seats=pdef.max_seats,
                max_storage_mb=pdef.max_storage_mb,
                is_active=True,
                display_order=pdef.display_order,
                features=pdef.features_summary,
                created_at=now,
                updated_at=now,
            )
            session.add(plan)
            await session.flush()
            print(f"  [plan] CREATED {pdef.slug!r}")
        else:
            # Refresh features summary on re-run
            plan.features = pdef.features_summary
            plan.updated_at = now
            print(f"  [plan] EXISTS  {pdef.slug!r} (features_summary refreshed)")

        # Upsert PlanFeature rows (skip disabled features: limit_value == -1)
        for key, limit in pdef.feature_limits.items():
            fid = feature_ids.get(key)
            if not fid:
                print(f"    WARNING: feature key {key!r} not found, skipping.")
                continue

            if limit == -1:
                # Feature explicitly disabled for this plan — remove row if present
                existing_pf = await session.execute(
                    select(PlanFeature).where(
                        PlanFeature.plan_id == plan.id,
                        PlanFeature.feature_id == fid,
                    )
                )
                pf_row = existing_pf.scalar_one_or_none()
                if pf_row:
                    await session.delete(pf_row)
                continue

            existing_pf = await session.execute(
                select(PlanFeature).where(
                    PlanFeature.plan_id == plan.id,
                    PlanFeature.feature_id == fid,
                )
            )
            pf_row = existing_pf.scalar_one_or_none()
            if pf_row:
                pf_row.limit_value = limit
                pf_row.updated_at = now
            else:
                pf = PlanFeature(
                    plan_id=plan.id,
                    feature_id=fid,
                    limit_value=limit,
                    created_at=now,
                    updated_at=now,
                )
                session.add(pf)

    await session.commit()
    print("Plans and plan-features seeded successfully.")


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async with factory() as session:
        print("Seeding features...")
        feature_ids = await seed_features(session)
        print("Seeding plans...")
        await seed_plans(session, feature_ids)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())


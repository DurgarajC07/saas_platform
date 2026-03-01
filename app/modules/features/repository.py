"""
Feature module repositories.

FeatureRepository           — CRUD for feature definitions
PlanFeatureRepository       — plan ↔ feature assignments
FeatureOverrideRepository   — org-level custom overrides
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, UTC
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.features.models import Feature, OrganizationFeatureOverride, PlanFeature


# ── FeatureRepository ─────────────────────────────────────────────────────

class FeatureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[Feature]:
        result = await self.session.execute(
            select(Feature).order_by(Feature.module, Feature.key)
        )
        return list(result.scalars().all())

    async def get_by_id(self, feature_id: UUID) -> Feature | None:
        result = await self.session.execute(
            select(Feature).where(Feature.id == feature_id)
        )
        return result.scalar_one_or_none()

    async def get_by_key(self, key: str) -> Feature | None:
        result = await self.session.execute(
            select(Feature).where(Feature.key == key)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        key: str,
        name: str | None = None,
        description: str | None = None,
        module: str | None = None,
    ) -> Feature:
        now = datetime.now(UTC)
        feat = Feature(
            id=_uuid.uuid4(),
            key=key,
            name=name,
            description=description,
            module=module,
            created_at=now,
            updated_at=now,
        )
        self.session.add(feat)
        await self.session.flush()
        await self.session.refresh(feat)
        return feat


# ── PlanFeatureRepository ─────────────────────────────────────────────────

class PlanFeatureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_plan(self, plan_id: UUID) -> list[PlanFeature]:
        result = await self.session.execute(
            select(PlanFeature)
            .where(PlanFeature.plan_id == plan_id)
            .options(selectinload(PlanFeature.feature))
        )
        return list(result.scalars().all())

    async def get(self, plan_id: UUID, feature_key: str) -> PlanFeature | None:
        """Return the PlanFeature row for a given plan + feature key (join via Feature)."""
        result = await self.session.execute(
            select(PlanFeature)
            .join(Feature, Feature.id == PlanFeature.feature_id)
            .where(
                PlanFeature.plan_id == plan_id,
                Feature.key == feature_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_feature_id(self, plan_id: UUID, feature_id: UUID) -> PlanFeature | None:
        result = await self.session.execute(
            select(PlanFeature).where(
                PlanFeature.plan_id == plan_id,
                PlanFeature.feature_id == feature_id,
            )
        )
        return result.scalar_one_or_none()

    async def assign(
        self,
        *,
        plan_id: UUID,
        feature_id: UUID,
        limit_value: int | None = None,
    ) -> PlanFeature:
        now = datetime.now(UTC)
        pf = PlanFeature(
            plan_id=plan_id,
            feature_id=feature_id,
            limit_value=limit_value,
            created_at=now,
            updated_at=now,
        )
        self.session.add(pf)
        await self.session.flush()
        return pf

    async def remove(self, plan_id: UUID, feature_id: UUID) -> None:
        await self.session.execute(
            delete(PlanFeature).where(
                PlanFeature.plan_id == plan_id,
                PlanFeature.feature_id == feature_id,
            )
        )
        await self.session.flush()


# ── FeatureOverrideRepository ─────────────────────────────────────────────

class FeatureOverrideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: UUID, feature_key: str) -> OrganizationFeatureOverride | None:
        """Return org override for a feature key (joins Feature table for key lookup)."""
        result = await self.session.execute(
            select(OrganizationFeatureOverride)
            .join(Feature, Feature.id == OrganizationFeatureOverride.feature_id)
            .where(
                OrganizationFeatureOverride.organization_id == org_id,
                Feature.key == feature_key,
            )
            .options(selectinload(OrganizationFeatureOverride.feature))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, override_id: UUID, org_id: UUID) -> OrganizationFeatureOverride | None:
        result = await self.session.execute(
            select(OrganizationFeatureOverride)
            .where(
                OrganizationFeatureOverride.id == override_id,
                OrganizationFeatureOverride.organization_id == org_id,
            )
            .options(selectinload(OrganizationFeatureOverride.feature))
        )
        return result.scalar_one_or_none()

    async def list_by_org(self, org_id: UUID) -> list[OrganizationFeatureOverride]:
        result = await self.session.execute(
            select(OrganizationFeatureOverride)
            .where(OrganizationFeatureOverride.organization_id == org_id)
            .options(selectinload(OrganizationFeatureOverride.feature))
            .order_by(OrganizationFeatureOverride.created_at)
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        org_id: UUID,
        feature_id: UUID,
        enabled: bool,
        limit_value: int | None,
        reason: str | None,
        expires_at: datetime | None,
    ) -> OrganizationFeatureOverride:
        """Create or update an org feature override (uq_org_feature_override guarantees one row)."""
        existing = await self.session.execute(
            select(OrganizationFeatureOverride).where(
                OrganizationFeatureOverride.organization_id == org_id,
                OrganizationFeatureOverride.feature_id == feature_id,
            )
        )
        override = existing.scalar_one_or_none()
        now = datetime.now(UTC)

        if override:
            override.enabled = enabled
            override.limit_value = limit_value
            override.reason = reason
            override.expires_at = expires_at
            override.updated_at = now
        else:
            override = OrganizationFeatureOverride(
                id=_uuid.uuid4(),
                organization_id=org_id,
                feature_id=feature_id,
                enabled=enabled,
                limit_value=limit_value,
                reason=reason,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            self.session.add(override)

        await self.session.flush()
        await self.session.refresh(override)
        return override

    async def delete(self, override_id: UUID, org_id: UUID) -> bool:
        """Returns True if a row was deleted."""
        result = await self.session.execute(
            delete(OrganizationFeatureOverride).where(
                OrganizationFeatureOverride.id == override_id,
                OrganizationFeatureOverride.organization_id == org_id,
            )
        )
        await self.session.flush()
        return result.rowcount > 0

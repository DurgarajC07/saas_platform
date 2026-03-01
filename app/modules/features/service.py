"""
Feature service — 3-level feature gate: override → plan → default-disabled.

Check hierarchy:
  1. OrganizationFeatureOverride   (enterprise deals / custom grants)
  2. PlanFeature row               (what the current subscription plan allows)
  3. Default: disabled             (no active subscription or feature not on plan)

Cache strategy:
  • Redis key ``feat:{org_id}`` caches the *full* feature map for the org.
  • TTL: ``FEATURE_CACHE_TTL`` (default 300 s, mirrors SUBSCRIPTION_CACHE_TTL).
  • Invalidated explicitly on:
      - subscription change   (BillingService calls invalidate_feature_cache)
      - override grant/delete (FeatureService.grant_override / delete_override)
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.config import get_settings
from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.repository import SubscriptionRepository
from app.modules.billing.models import SubscriptionPlan
from app.modules.features.models import Feature, OrganizationFeatureOverride, PlanFeature
from app.modules.features.repository import (
    FeatureOverrideRepository,
    FeatureRepository,
    PlanFeatureRepository,
)
from app.modules.features.schemas import (
    AssignPlanFeatureRequest,
    CreateFeatureRequest,
    FeatureCheckResult,
    FeatureListResponse,
    FeatureResponse,
    GrantOverrideRequest,
    OverrideListResponse,
    OverrideResponse,
    PlanFeatureResponse,
)

logger = structlog.get_logger(__name__)

_SETTINGS = None


def _get_settings():
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = get_settings()
    return _SETTINGS


def _feature_cache_key(org_id: UUID) -> str:
    return f"feat:{org_id}"


class FeatureService:
    def __init__(
        self,
        session: AsyncSession,
        redis: aioredis.Redis,
    ) -> None:
        self._session = session
        self._redis = redis
        self._feat_repo = FeatureRepository(session)
        self._plan_feat_repo = PlanFeatureRepository(session)
        self._override_repo = FeatureOverrideRepository(session)
        self._sub_repo = SubscriptionRepository(session)
        self._audit = AuditService(session)

    # ── Cache helpers ─────────────────────────────────────────────────────

    async def invalidate_feature_cache(self, org_id: UUID) -> None:
        await self._redis.delete(_feature_cache_key(org_id))
        logger.debug("features.cache_invalidated", org_id=str(org_id))

    async def _get_cached_map(self, org_id: UUID) -> dict[str, dict] | None:
        raw = await self._redis.get(_feature_cache_key(org_id))
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def _cache_map(self, org_id: UUID, feature_map: dict[str, dict]) -> None:
        ttl = _get_settings().SUBSCRIPTION_CACHE_TTL
        await self._redis.setex(
            _feature_cache_key(org_id),
            ttl,
            json.dumps(feature_map),
        )

    # ── Core check ────────────────────────────────────────────────────────

    async def check(self, org_id: UUID, feature_key: str) -> FeatureCheckResult:
        """
        Check a single feature for an org using the 3-level hierarchy.
        Uses in-memory cache from ``_build_feature_map`` if already resolved;
        does NOT use Redis here to keep hot-path latency low for individual checks.
        """
        feat_map = await self._build_feature_map(org_id)
        entry = feat_map.get(feature_key)
        if not entry:
            return FeatureCheckResult(feature_key=feature_key, enabled=False, limit=0)
        return FeatureCheckResult(
            feature_key=feature_key,
            enabled=entry["enabled"],
            limit=entry.get("limit"),
        )

    async def require(self, org_id: UUID, feature_key: str) -> None:
        """Raise ForbiddenException if the feature is not accessible to the org."""
        result = await self.check(org_id, feature_key)
        if not result.enabled:
            raise ForbiddenException(f"Feature not available on current plan: {feature_key}")

    async def check_many(
        self, org_id: UUID, keys: list[str]
    ) -> dict[str, FeatureCheckResult]:
        """Check multiple feature keys in one DB round-trip (single feature_map build)."""
        feat_map = await self._build_feature_map(org_id)
        results: dict[str, FeatureCheckResult] = {}
        for key in keys:
            entry = feat_map.get(key)
            if entry:
                results[key] = FeatureCheckResult(
                    feature_key=key,
                    enabled=entry["enabled"],
                    limit=entry.get("limit"),
                )
            else:
                results[key] = FeatureCheckResult(feature_key=key, enabled=False, limit=0)
        return results

    # ── Feature map builder ───────────────────────────────────────────────

    async def _build_feature_map(self, org_id: UUID) -> dict[str, dict]:
        """
        Build + cache the full feature map for an org.  Result shape:
          { "feature.key": {"enabled": bool, "limit": int|None} }

        Resolution order:
          1. Active org overrides (skip expired ones at query time)
          2. Plan features from the active subscription

        Redis cache is populated after first build.
        """
        cached = await self._get_cached_map(org_id)
        if cached is not None:
            return cached

        feat_map: dict[str, dict] = {}

        # ── Level 1: org overrides ────────────────────────────────────────
        now = datetime.now(UTC)
        overrides = await self._override_repo.list_by_org(org_id)
        for ov in overrides:
            # Skip expired overrides (lazy expiry — no cron needed)
            if ov.expires_at and ov.expires_at <= now:
                continue
            if ov.feature:
                feat_map[ov.feature.key] = {
                    "enabled": ov.enabled,
                    "limit": ov.limit_value,
                    "source": "override",
                }

        # ── Level 2: plan features ────────────────────────────────────────
        sub = await self._sub_repo.get_active_by_org(org_id)
        if sub:
            plan_features = await self._plan_feat_repo.list_by_plan(sub.plan_id)
            for pf in plan_features:
                if pf.feature and pf.feature.key not in feat_map:
                    # Override already set above takes precedence
                    feat_map[pf.feature.key] = {
                        "enabled": True,
                        "limit": pf.limit_value,
                        "source": "plan",
                    }

        await self._cache_map(org_id, feat_map)
        return feat_map

    # ── Feature CRUD (platform admin) ─────────────────────────────────────

    async def list_features(self) -> FeatureListResponse:
        feats = await self._feat_repo.list_all()
        return FeatureListResponse(
            features=[FeatureResponse.model_validate(f) for f in feats],
            total=len(feats),
        )

    async def create_feature(
        self,
        data: CreateFeatureRequest,
        actor: User,
        request: Request,
    ) -> FeatureResponse:
        _require_platform_admin(actor)
        existing = await self._feat_repo.get_by_key(data.key)
        if existing:
            raise ConflictException(f"Feature with key '{data.key}' already exists")

        feat = await self._feat_repo.create(
            key=data.key,
            name=data.name,
            description=data.description,
            module=data.module,
        )
        await self._audit.log(
            action="features.feature.create",
            resource_type="feature",
            resource_id=feat.id,
            actor_user_id=actor.id,
            request=request,
            new_values={"key": feat.key, "module": feat.module},
            description=f"Created feature '{feat.key}'",
        )
        logger.info("features.created", key=feat.key)
        return FeatureResponse.model_validate(feat)

    # ── Plan-feature management (platform admin) ──────────────────────────

    async def assign_plan_feature(
        self,
        plan_id: UUID,
        data: AssignPlanFeatureRequest,
        actor: User,
        request: Request,
    ) -> PlanFeatureResponse:
        _require_platform_admin(actor)

        feat = await self._feat_repo.get_by_id(data.feature_id)
        if not feat:
            raise NotFoundException("Feature not found")

        existing = await self._plan_feat_repo.get_by_feature_id(plan_id, data.feature_id)
        if existing:
            # Update limit instead of raising conflict
            existing.limit_value = data.limit_value
            existing.updated_at = datetime.now(UTC)
            await self._session.flush()
            pf = existing
        else:
            pf = await self._plan_feat_repo.assign(
                plan_id=plan_id,
                feature_id=data.feature_id,
                limit_value=data.limit_value,
            )

        await self._audit.log(
            action="features.plan_feature.assign",
            resource_type="plan_feature",
            resource_id=plan_id,
            actor_user_id=actor.id,
            request=request,
            new_values={"feature_key": feat.key, "limit_value": data.limit_value},
            description=f"Assigned feature '{feat.key}' to plan {plan_id}",
        )
        logger.info("features.plan_feature.assigned", plan_id=str(plan_id), feature=feat.key)
        return PlanFeatureResponse(
            plan_id=pf.plan_id,
            feature_id=pf.feature_id,
            feature_key=feat.key,
            feature_name=feat.name,
            limit_value=pf.limit_value,
            created_at=pf.created_at,
        )

    # ── Override management (platform admin) ──────────────────────────────

    async def grant_override(
        self,
        org_id: UUID,
        data: GrantOverrideRequest,
        actor: User,
        request: Request,
    ) -> OverrideResponse:
        _require_platform_admin(actor)

        feat = await self._feat_repo.get_by_id(data.feature_id)
        if not feat:
            raise NotFoundException("Feature not found")

        override = await self._override_repo.upsert(
            org_id=org_id,
            feature_id=data.feature_id,
            enabled=data.enabled,
            limit_value=data.limit_value,
            reason=data.reason,
            expires_at=data.expires_at,
        )
        # Reload with feature relationship
        override = await self._override_repo.get_by_id(override.id, org_id)

        # Invalidate cache so next check sees the new override
        await self.invalidate_feature_cache(org_id)

        await self._audit.log(
            action="features.override.grant",
            resource_type="feature_override",
            resource_id=override.id,
            actor_user_id=actor.id,
            request=request,
            new_values={
                "feature_key": feat.key,
                "enabled": data.enabled,
                "limit_value": data.limit_value,
                "expires_at": data.expires_at.isoformat() if data.expires_at else None,
            },
            description=f"Granted feature override '{feat.key}' to org {org_id}",
        )
        logger.info(
            "features.override.granted",
            org_id=str(org_id),
            feature=feat.key,
            enabled=data.enabled,
        )
        return _override_to_schema(override)

    async def delete_override(
        self,
        override_id: UUID,
        org_id: UUID,
        actor: User,
        request: Request,
    ) -> None:
        _require_platform_admin(actor)

        override = await self._override_repo.get_by_id(override_id, org_id)
        if not override:
            raise NotFoundException("Feature override not found")

        feature_key = override.feature.key if override.feature else str(override.feature_id)
        deleted = await self._override_repo.delete(override_id, org_id)
        if not deleted:
            raise NotFoundException("Feature override not found")

        await self.invalidate_feature_cache(org_id)

        await self._audit.log(
            action="features.override.delete",
            resource_type="feature_override",
            resource_id=override_id,
            actor_user_id=actor.id,
            request=request,
            old_values={"feature_key": feature_key},
            description=f"Removed feature override '{feature_key}' from org {org_id}",
        )
        logger.info("features.override.deleted", org_id=str(org_id), feature=feature_key)

    async def list_org_overrides(
        self,
        org_id: UUID,
    ) -> OverrideListResponse:
        overrides = await self._override_repo.list_by_org(org_id)
        items = [_override_to_schema(ov) for ov in overrides]
        return OverrideListResponse(overrides=items, total=len(items))


# ── Helpers ───────────────────────────────────────────────────────────────

def _require_platform_admin(user: User) -> None:
    if not getattr(user, "is_platform_admin", False):
        raise ForbiddenException("Platform admin access required")


def _override_to_schema(ov: OrganizationFeatureOverride) -> OverrideResponse:
    return OverrideResponse(
        id=ov.id,
        organization_id=ov.organization_id,
        feature_id=ov.feature_id,
        feature_key=ov.feature.key if ov.feature else "",
        enabled=ov.enabled,
        limit_value=ov.limit_value,
        reason=ov.reason,
        expires_at=ov.expires_at,
        created_at=ov.created_at,
        updated_at=ov.updated_at,
    )

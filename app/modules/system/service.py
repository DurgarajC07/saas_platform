"""
System Settings service.

Responsibilities:
  • Redis-cached get / set / list for SystemSettings.
  • Health-check probe (DB, Redis, disk).
  • Admin aggregate stats.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.modules.system.models import SystemSetting
from app.modules.system.repository import SystemSettingRepository
from app.modules.system.schemas import (
    AdminStatsResponse,
    DiskUsage,
    HealthComponentStatus,
    HealthResponse,
    SystemSettingListResponse,
    SystemSettingResponse,
    UpdateSettingRequest,
)

logger = structlog.get_logger(__name__)

_CACHE_PREFIX = "system:settings:"
_CACHE_TTL = 600  # 10 minutes


def _cache_key(key: str) -> str:
    return f"{_CACHE_PREFIX}{key}"


class SystemService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SystemSettingRepository(session)

    # ── Public helpers ────────────────────────────────────────────────────

    async def get_value(self, key: str) -> Any | None:
        """Return the parsed JSONB value for *key*, using Redis cache."""
        redis = await get_redis()
        raw = await redis.get(_cache_key(key))
        if raw is not None:
            return json.loads(raw)

        setting = await self.repo.get_by_key(key)
        if setting is None:
            return None

        await redis.setex(_cache_key(key), _CACHE_TTL, json.dumps(setting.value))
        return setting.value

    async def get_setting(self, key: str) -> SystemSettingResponse | None:
        """Return the full setting DTO (bypasses value-only cache)."""
        setting = await self.repo.get_by_key(key)
        if setting is None:
            return None
        return SystemSettingResponse.model_validate(setting)

    async def list_settings(
        self, *, public_only: bool = False
    ) -> SystemSettingListResponse:
        rows = await self.repo.list_all(public_only=public_only)
        items = [SystemSettingResponse.model_validate(r) for r in rows]
        return SystemSettingListResponse(settings=items, count=len(items))

    async def upsert_setting(
        self,
        key: str,
        payload: UpdateSettingRequest,
        *,
        updated_by: UUID | None = None,
    ) -> SystemSettingResponse:
        setting = await self.repo.upsert(
            key=key,
            value=payload.value,
            description=payload.description,
            is_public=payload.is_public,
            updated_by=updated_by,
        )
        await self.session.commit()
        await self.session.refresh(setting)

        # Invalidate cache
        redis = await get_redis()
        await redis.delete(_cache_key(key))

        logger.info("system.setting.updated", key=key, updated_by=str(updated_by))
        return SystemSettingResponse.model_validate(setting)

    async def delete_setting(self, key: str) -> bool:
        deleted = await self.repo.delete_by_key(key)
        if deleted:
            await self.session.commit()
            redis = await get_redis()
            await redis.delete(_cache_key(key))
            logger.info("system.setting.deleted", key=key)
        return deleted

    # ── Health check ──────────────────────────────────────────────────────

    async def health_check(self) -> HealthResponse:
        from app.config import get_settings

        cfg = get_settings()
        components: dict[str, HealthComponentStatus] = {}
        overall_ok = True

        # Database
        db_start = time.monotonic()
        try:
            await self.session.execute(select(1))
            components["database"] = HealthComponentStatus(
                status="ok",
                latency_ms=round((time.monotonic() - db_start) * 1000, 2),
            )
        except Exception as exc:
            overall_ok = False
            components["database"] = HealthComponentStatus(
                status="down",
                detail=str(exc),
            )

        # Redis
        redis_start = time.monotonic()
        try:
            redis = await get_redis()
            await redis.ping()
            components["redis"] = HealthComponentStatus(
                status="ok",
                latency_ms=round((time.monotonic() - redis_start) * 1000, 2),
            )
        except Exception as exc:
            overall_ok = False
            components["redis"] = HealthComponentStatus(
                status="down",
                detail=str(exc),
            )

        # Disk
        disk_usage = shutil.disk_usage("/")
        disk = DiskUsage(
            total_gb=round(disk_usage.total / 1e9, 2),
            used_gb=round(disk_usage.used / 1e9, 2),
            free_gb=round(disk_usage.free / 1e9, 2),
            percent_used=round(disk_usage.used / disk_usage.total * 100, 1),
        )
        if disk.percent_used > 90:
            overall_ok = False
            components["disk"] = HealthComponentStatus(
                status="degraded",
                detail=f"{disk.percent_used}% used",
            )
        else:
            components["disk"] = HealthComponentStatus(
                status="ok",
                detail=f"{disk.free_gb} GB free",
            )

        return HealthResponse(
            status="healthy" if overall_ok else "degraded",
            version=getattr(cfg, "APP_VERSION", "0.1.0"),
            environment=getattr(cfg, "APP_ENV", "development"),
            timestamp=datetime.now(UTC),
            components=components,
            disk=disk,
        )

    # ── Admin stats ───────────────────────────────────────────────────────

    async def admin_stats(self) -> AdminStatsResponse:
        from app.modules.auth.models import User
        from app.modules.billing.models import Subscription, SubscriptionPlan
        from app.modules.files.models import File
        from app.modules.tenancy.models import Organization

        now = datetime.now(UTC)
        thirty_days_ago = now - timedelta(days=30)

        # Users
        total_users = await self.session.scalar(
            select(func.count()).select_from(User)
        ) or 0
        active_users = await self.session.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        ) or 0
        new_users_30d = await self.session.scalar(
            select(func.count()).select_from(User).where(
                User.created_at >= thirty_days_ago
            )
        ) or 0

        # Organisations (active = is_active=True)
        total_orgs = await self.session.scalar(
            select(func.count()).select_from(Organization)
        ) or 0
        active_orgs = await self.session.scalar(
            select(func.count()).select_from(Organization).where(
                Organization.is_active.is_(True)
            )
        ) or 0
        new_orgs_30d = await self.session.scalar(
            select(func.count()).select_from(Organization).where(
                Organization.created_at >= thirty_days_ago
            )
        ) or 0

        # Active subscriptions count
        active_subs = await self.session.scalar(
            select(func.count()).select_from(Subscription).where(
                Subscription.status == "active"
            )
        ) or 0

        # MRR: join subscriptions → plans for pricing
        # Monthly billed: sum(plan.price_monthly)
        mrr_monthly = await self.session.scalar(
            select(func.coalesce(func.sum(SubscriptionPlan.price_monthly), 0.0))
            .join(Subscription, Subscription.plan_id == SubscriptionPlan.id)
            .where(
                Subscription.status == "active",
                Subscription.billing_cycle == "monthly",
            )
        ) or 0.0
        # Yearly billed: sum(plan.price_yearly); ARR = that sum, MRR contribution = /12
        arr_yearly = await self.session.scalar(
            select(func.coalesce(func.sum(SubscriptionPlan.price_yearly), 0.0))
            .join(Subscription, Subscription.plan_id == SubscriptionPlan.id)
            .where(
                Subscription.status == "active",
                Subscription.billing_cycle == "yearly",
            )
        ) or 0.0
        mrr = float(mrr_monthly) + float(arr_yearly) / 12
        arr = mrr * 12

        # Files — SoftDeleteMixin: not deleted = deleted_at IS NULL
        total_files = await self.session.scalar(
            select(func.count()).select_from(File).where(
                File.deleted_at.is_(None)
            )
        ) or 0
        total_file_size = await self.session.scalar(
            select(func.coalesce(func.sum(File.file_size_bytes), 0)).where(
                File.deleted_at.is_(None)
            )
        ) or 0

        return AdminStatsResponse(
            total_users=total_users,
            active_users=active_users,
            total_organizations=total_orgs,
            active_organizations=active_orgs,
            total_files=total_files,
            total_file_size_bytes=int(total_file_size),
            active_subscriptions=active_subs,
            mrr_usd=round(mrr, 2),
            arr_usd=round(arr, 2),
            period_new_users_30d=new_users_30d,
            period_new_orgs_30d=new_orgs_30d,
        )

"""
Billing service — subscription lifecycle, plan management, invoice tracking,
payment methods, and Stripe webhook handling.

Architecture:
  • Subscription status cached at ``sub:{org_id}`` (TTL 5 min) for fast
    feature-gate checks without hitting the DB.
  • Payment provider is injected at construction time via the adapter pattern
    (defaults to the configured provider from settings).
  • All mutating operations emit audit log entries.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, UTC
from decimal import Decimal
from uuid import UUID

import structlog
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.config import get_settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.billing.constants import (
    BillingCycle,
    InvoiceStatus,
    StripeEvent,
    SubscriptionStatus,
    subscription_cache_key,
)
from app.modules.billing.models import Invoice, PaymentMethod, Subscription, SubscriptionPlan
from app.modules.billing.providers.base import PaymentProviderBase
from app.modules.billing.repository import (
    InvoiceRepository,
    PaymentMethodRepository,
    SubscriptionPlanRepository,
    SubscriptionRepository,
)
from app.modules.billing.schemas import (
    AddPaymentMethodRequest,
    BillingUsageResponse,
    CancelSubscriptionRequest,
    CreatePlanRequest,
    InvoiceLineItem,
    InvoiceListResponse,
    InvoicePreviewResponse,
    InvoiceResponse,
    PaymentMethodListResponse,
    PaymentMethodResponse,
    PlanListResponse,
    PlanResponse,
    SubscribeRequest,
    SubscriptionListResponse,
    SubscriptionResponse,
    UpdatePlanRequest,
)
from app.shared.base_schemas import PaginationMeta

logger = structlog.get_logger(__name__)

_SETTINGS = None


def _get_settings():
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = get_settings()
    return _SETTINGS


class BillingService:
    def __init__(
        self,
        session: AsyncSession,
        redis: aioredis.Redis,
        provider: PaymentProviderBase | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self._plan_repo = SubscriptionPlanRepository(session)
        self._sub_repo = SubscriptionRepository(session)
        self._inv_repo = InvoiceRepository(session)
        self._pm_repo = PaymentMethodRepository(session)
        self._audit = AuditService(session)

        # Lazy-load provider to avoid circular imports at module-level
        if provider is None:
            from app.modules.billing.providers import get_provider
            provider = get_provider()
        self._provider = provider

    # ── Subscription cache ────────────────────────────────────────────────

    async def _cache_subscription(self, sub: Subscription) -> None:
        """Store a compact subscription snapshot in Redis."""
        settings = _get_settings()
        payload = {
            "id": str(sub.id),
            "status": sub.status,
            "plan_id": str(sub.plan_id),
            "billing_cycle": sub.billing_cycle,
            "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        }
        await self.redis.set(
            subscription_cache_key(sub.organization_id),
            json.dumps(payload),
            ex=settings.SUBSCRIPTION_CACHE_TTL,
        )

    async def _invalidate_subscription_cache(self, org_id: UUID) -> None:
        await self.redis.delete(subscription_cache_key(org_id))

    async def _invalidate_feature_cache(self, org_id: UUID) -> None:
        """Invalidate the feature gate cache when a subscription changes."""
        await self.redis.delete(f"feat:{org_id}")

    async def get_cached_subscription(self, org_id: UUID) -> dict | None:
        """Return the cached subscription snapshot or None on cache miss."""
        raw = await self.redis.get(subscription_cache_key(org_id))
        if raw:
            return json.loads(raw)
        return None

    # ── Plans ─────────────────────────────────────────────────────────────

    async def list_plans(self, *, admin: bool = False) -> PlanListResponse:
        plans = await self._plan_repo.list_all() if admin else await self._plan_repo.list_active()
        schemas = [PlanResponse.model_validate(p) for p in plans]
        return PlanListResponse(plans=schemas, total=len(schemas))

    async def get_plan(self, plan_id: UUID) -> PlanResponse:
        plan = await self._plan_repo.get_by_id(plan_id)
        if not plan:
            raise NotFoundException("Plan not found")
        return PlanResponse.model_validate(plan)

    async def create_plan(
        self,
        data: CreatePlanRequest,
        actor: User,
        request: Request,
    ) -> PlanResponse:
        self._require_platform_admin(actor)

        if await self._plan_repo.get_by_slug(data.slug):
            raise ConflictException(f"A plan with slug '{data.slug}' already exists")

        plan = await self._plan_repo.create(
            name=data.name,
            slug=data.slug,
            description=data.description,
            price_monthly=data.price_monthly,
            price_yearly=data.price_yearly,
            currency=data.currency,
            trial_days=data.trial_days,
            max_seats=data.max_seats,
            max_storage_mb=data.max_storage_mb,
            display_order=data.display_order,
            features=data.features,
        )
        await self._audit.log(
            action="billing.plan.create",
            resource_type="subscription_plan",
            resource_id=plan.id,
            actor_user_id=actor.id,
            request=request,
            new_values={"slug": plan.slug, "name": plan.name},
            description=f"Created plan '{plan.name}'",
        )
        return PlanResponse.model_validate(plan)

    async def update_plan(
        self,
        plan_id: UUID,
        data: UpdatePlanRequest,
        actor: User,
        request: Request,
    ) -> PlanResponse:
        self._require_platform_admin(actor)

        plan = await self._plan_repo.get_by_id(plan_id)
        if not plan:
            raise NotFoundException("Plan not found")

        old = {"name": plan.name, "is_active": plan.is_active}
        plan = await self._plan_repo.update(
            plan,
            **{k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None},
        )
        await self._audit.log(
            action="billing.plan.update",
            resource_type="subscription_plan",
            resource_id=plan.id,
            actor_user_id=actor.id,
            request=request,
            old_values=old,
            new_values={"name": plan.name, "is_active": plan.is_active},
            description=f"Updated plan '{plan.name}'",
        )
        return PlanResponse.model_validate(plan)

    async def delete_plan(
        self,
        plan_id: UUID,
        actor: User,
        request: Request,
    ) -> None:
        self._require_platform_admin(actor)
        plan = await self._plan_repo.get_by_id(plan_id)
        if not plan:
            raise NotFoundException("Plan not found")

        await self._plan_repo.deactivate(plan)
        await self._audit.log(
            action="billing.plan.delete",
            resource_type="subscription_plan",
            resource_id=plan.id,
            actor_user_id=actor.id,
            request=request,
            old_values={"slug": plan.slug},
            description=f"Deactivated plan '{plan.name}'",
        )

    # ── Subscriptions ─────────────────────────────────────────────────────

    async def get_subscription(self, org_id: UUID) -> SubscriptionResponse | None:
        """
        Return the active/trialing subscription for the org.
        Checks Redis cache first; falls back to DB and re-populates cache.
        """
        # Try cache first for fast reads
        cached = await self.get_cached_subscription(org_id)
        if cached and cached.get("status") in SubscriptionStatus.ACTIVE_STATUSES:
            # Cache hit — load full record for complete response
            sub = await self._sub_repo.get_by_id(UUID(cached["id"]))
            if sub:
                return self._sub_to_schema(sub)

        # DB fallback
        sub = await self._sub_repo.get_active_by_org(org_id)
        if not sub:
            return None
        await self._cache_subscription(sub)
        return self._sub_to_schema(sub)

    async def subscribe(
        self,
        org_id: UUID,
        data: SubscribeRequest,
        actor: User,
        request: Request,
    ) -> SubscriptionResponse:
        """
        Create or replace the active subscription for an org.
        Handles free and paid tiers; sets trialing status when plan.trial_days > 0.
        """
        plan = await self._plan_repo.get_by_id(data.plan_id)
        if not plan or not plan.is_active:
            raise NotFoundException("Plan not found or inactive")

        if data.billing_cycle not in BillingCycle.ALL:
            raise BadRequestException(f"billing_cycle must be one of: {BillingCycle.ALL}")

        # Cancel existing active subscription first
        existing = await self._sub_repo.get_active_by_org(org_id)
        if existing:
            await self._sub_repo.update(
                existing,
                status=SubscriptionStatus.CANCELED,
                canceled_at=datetime.now(UTC),
                cancellation_reason="Replaced by new subscription",
            )

        # Determine trial
        trial_end: datetime | None = None
        if plan.trial_days > 0:
            trial_end = datetime.now(UTC) + timedelta(days=plan.trial_days)

        # Calculate period end
        now = datetime.now(UTC)
        period_end = now + timedelta(days=365 if data.billing_cycle == BillingCycle.YEARLY else 30)

        status = SubscriptionStatus.TRIALING if trial_end else SubscriptionStatus.ACTIVE

        sub = await self._sub_repo.create(
            organization_id=org_id,
            plan_id=plan.id,
            status=status,
            billing_cycle=data.billing_cycle,
            current_period_start=now,
            current_period_end=period_end,
            trial_ends_at=trial_end,
            external_customer_id=data.external_customer_id,
        )

        # Create invoice for paid plans (skip for free tier and trial)
        price = plan.price_yearly if data.billing_cycle == BillingCycle.YEARLY else plan.price_monthly
        if price and price > Decimal("0") and not trial_end:
            inv_number = await self._inv_repo.next_invoice_number()
            await self._inv_repo.create(
                organization_id=org_id,
                subscription_id=sub.id,
                invoice_number=inv_number,
                amount=price,
                currency=plan.currency,
                status=InvoiceStatus.PENDING,
                due_date=now + timedelta(days=30),
                billing_details={"plan_slug": plan.slug, "billing_cycle": data.billing_cycle},
            )

        await self._cache_subscription(sub)
        # Invalidate feature cache so next check reflects new plan
        await self._invalidate_feature_cache(org_id)

        await self._audit.log(
            action="billing.subscription.create",
            resource_type="subscription",
            resource_id=sub.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            new_values={"plan": plan.slug, "status": status, "cycle": data.billing_cycle},
            description=f"Subscribed to plan '{plan.slug}' ({data.billing_cycle})",
        )
        logger.info("billing.subscribed", org_id=str(org_id), plan=plan.slug, status=status)

        # Reload with plan relationship
        sub = await self._sub_repo.get_by_id(sub.id)
        return self._sub_to_schema(sub)

    async def cancel_subscription(
        self,
        org_id: UUID,
        data: CancelSubscriptionRequest,
        actor: User,
        request: Request,
    ) -> SubscriptionResponse:
        sub = await self._sub_repo.get_active_by_org(org_id)
        if not sub:
            raise NotFoundException("No active subscription found")

        # Cancel via external provider if wired
        if sub.external_subscription_id:
            try:
                await self._provider.cancel_subscription(
                    sub.external_subscription_id,
                    at_period_end=data.at_period_end,
                )
            except Exception as exc:
                logger.warning("billing.provider_cancel_failed", error=str(exc))

        if data.at_period_end:
            # Keep active until period end; mark canceled_at for tracking
            sub = await self._sub_repo.update(
                sub,
                canceled_at=datetime.now(UTC),
                cancellation_reason=data.reason,
            )
        else:
            sub = await self._sub_repo.update(
                sub,
                status=SubscriptionStatus.CANCELED,
                canceled_at=datetime.now(UTC),
                cancellation_reason=data.reason,
            )

        await self._invalidate_subscription_cache(org_id)
        await self._invalidate_feature_cache(sub.organization_id)
        await self._audit.log(
            action="billing.subscription.cancel",
            resource_type="subscription",
            resource_id=sub.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            new_values={"at_period_end": data.at_period_end, "reason": data.reason},
            description="Subscription cancellation requested",
        )
        sub = await self._sub_repo.get_by_id(sub.id)
        return self._sub_to_schema(sub)

    async def list_subscriptions(self, org_id: UUID) -> SubscriptionListResponse:
        subs = await self._sub_repo.list_by_org(org_id)
        return SubscriptionListResponse(
            subscriptions=[self._sub_to_schema(s) for s in subs],
            total=len(subs),
        )

    # ── Invoices ──────────────────────────────────────────────────────────

    async def list_invoices(
        self, org_id: UUID, page: int = 1, page_size: int = 20
    ) -> InvoiceListResponse:
        offset = (page - 1) * page_size
        invoices, total = await self._inv_repo.list_by_org(
            org_id, offset=offset, limit=page_size
        )
        total_pages = max(1, math.ceil(total / page_size)) if total else 1
        return InvoiceListResponse(
            invoices=[InvoiceResponse.model_validate(i) for i in invoices],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=offset + page_size < total,
                has_previous=page > 1,
            ),
        )

    async def get_invoice(self, invoice_id: UUID, org_id: UUID) -> InvoiceResponse:
        inv = await self._inv_repo.get_by_id(invoice_id, org_id)
        if not inv:
            raise NotFoundException("Invoice not found")
        return InvoiceResponse.model_validate(inv)

    # ── Payment methods ───────────────────────────────────────────────────

    async def list_payment_methods(self, org_id: UUID) -> PaymentMethodListResponse:
        pms = await self._pm_repo.list_by_org(org_id)
        return PaymentMethodListResponse(
            payment_methods=[PaymentMethodResponse.model_validate(p) for p in pms],
            total=len(pms),
        )

    async def add_payment_method(
        self,
        org_id: UUID,
        data: AddPaymentMethodRequest,
        actor: User,
        request: Request,
    ) -> PaymentMethodResponse:
        pm = await self._pm_repo.create(
            organization_id=org_id,
            type=data.type,
            provider=data.provider or _get_settings().BILLING_PROVIDER,
            external_payment_method_id=data.external_payment_method_id,
            last_four=data.last_four,
            card_brand=data.card_brand,
            expires_month=data.expires_month,
            expires_year=data.expires_year,
            billing_address=data.billing_address,
            is_default=data.set_as_default,
        )
        if data.set_as_default:
            await self._pm_repo.clear_default(org_id)
            pm.is_default = True

        await self._audit.log(
            action="billing.payment_method.add",
            resource_type="payment_method",
            resource_id=pm.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            new_values={"type": pm.type, "last_four": pm.last_four},
            description="Added payment method",
        )
        # Reload to ensure server-computed columns (updated_at via onupdate) are fresh
        pm = await self._pm_repo.get_by_id(pm.id, org_id)
        return PaymentMethodResponse.model_validate(pm)

    async def set_default_payment_method(
        self,
        pm_id: UUID,
        org_id: UUID,
        actor: User,
        request: Request,
    ) -> PaymentMethodResponse:
        pm = await self._pm_repo.get_by_id(pm_id, org_id)
        if not pm:
            raise NotFoundException("Payment method not found")
        pm = await self._pm_repo.set_default(pm)
        await self._audit.log(
            action="billing.payment_method.set_default",
            resource_type="payment_method",
            resource_id=pm.id,
            org_id=org_id,
            actor_user_id=actor.id,
            request=request,
            description="Set default payment method",
        )
        pm = await self._pm_repo.get_by_id(pm.id, org_id)
        return PaymentMethodResponse.model_validate(pm)

    # ── Stripe webhook handling ───────────────────────────────────────────

    async def handle_stripe_webhook(self, event_type: str, data: dict) -> None:
        """
        Dispatch an incoming Stripe event to the appropriate handler.
        Unknown events are silently ignored (Stripe sends many event types).
        """
        handlers = {
            StripeEvent.INVOICE_PAID: self._handle_invoice_paid,
            StripeEvent.INVOICE_PAYMENT_FAILED: self._handle_payment_failed,
            StripeEvent.SUBSCRIPTION_DELETED: self._handle_subscription_canceled,
            StripeEvent.SUBSCRIPTION_UPDATED: self._handle_subscription_updated,
        }
        handler = handlers.get(event_type)
        if handler:
            await handler(data)
        logger.info("billing.stripe_webhook", stripe_event=event_type)

    async def _handle_invoice_paid(self, data: dict) -> None:
        """Mark an invoice as paid; mark subscription active if past_due."""
        obj = data.get("object", data)
        external_inv_id = obj.get("id")
        external_sub_id = obj.get("subscription")

        if external_inv_id:
            inv = await self._inv_repo.get_by_external_id(external_inv_id)
            if inv:
                await self._inv_repo.update(
                    inv,
                    status=InvoiceStatus.PAID,
                    paid_at=datetime.now(UTC),
                )

        if external_sub_id:
            sub = await self._sub_repo.get_by_external_id(external_sub_id)
            if sub and sub.status == SubscriptionStatus.PAST_DUE:
                await self._sub_repo.update(sub, status=SubscriptionStatus.ACTIVE)
                await self._invalidate_subscription_cache(sub.organization_id)

    async def _handle_payment_failed(self, data: dict) -> None:
        obj = data.get("object", data)
        external_sub_id = obj.get("subscription")
        if external_sub_id:
            sub = await self._sub_repo.get_by_external_id(external_sub_id)
            if sub:
                await self._sub_repo.update(sub, status=SubscriptionStatus.PAST_DUE)
                await self._invalidate_subscription_cache(sub.organization_id)
                logger.warning(
                    "billing.payment_failed",
                    org_id=str(sub.organization_id),
                    sub_id=str(sub.id),
                )

    async def _handle_subscription_canceled(self, data: dict) -> None:
        obj = data.get("object", data)
        external_sub_id = obj.get("id")
        if external_sub_id:
            sub = await self._sub_repo.get_by_external_id(external_sub_id)
            if sub:
                await self._sub_repo.update(
                    sub,
                    status=SubscriptionStatus.CANCELED,
                    canceled_at=datetime.now(UTC),
                )
                await self._invalidate_subscription_cache(sub.organization_id)

    async def _handle_subscription_updated(self, data: dict) -> None:
        """Sync period dates and status after a Stripe subscription update."""
        obj = data.get("object", data)
        external_sub_id = obj.get("id")
        if not external_sub_id:
            return
        sub = await self._sub_repo.get_by_external_id(external_sub_id)
        if not sub:
            return

        stripe_status = obj.get("status", sub.status)
        # Map Stripe statuses to our internal statuses
        status_map = {
            "active": SubscriptionStatus.ACTIVE,
            "trialing": SubscriptionStatus.TRIALING,
            "past_due": SubscriptionStatus.PAST_DUE,
            "canceled": SubscriptionStatus.CANCELED,
            "incomplete": SubscriptionStatus.INCOMPLETE,
        }
        new_status = status_map.get(stripe_status, sub.status)

        updates: dict = {"status": new_status}
        if obj.get("current_period_end"):
            updates["current_period_end"] = datetime.fromtimestamp(
                obj["current_period_end"], tz=UTC
            )
        await self._sub_repo.update(sub, **updates)
        await self._invalidate_subscription_cache(sub.organization_id)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _sub_to_schema(sub: Subscription | None) -> SubscriptionResponse | None:
        if not sub:
            return None
        return SubscriptionResponse.model_validate(sub)

    # ── Usage & invoice preview ──────────────────────────────────────────

    async def get_usage(self, org_id: UUID) -> BillingUsageResponse:
        """
        Return current-month call-minute consumption for *org_id*.

        Reads the Redis counter written by ``CallCreditService`` and the
        active subscription plan for the monthly quota.
        """
        from app.modules.agents.credits import CallCreditService

        credit_svc = CallCreditService(self._session, self._redis)
        usage = await credit_svc.get_usage(org_id)  # MinutesUsage namedtuple

        sub = await self._sub_repo.get_active(org_id)
        plan_name = sub.plan.name if (sub and sub.plan) else "free"

        ym = datetime.now(UTC).strftime("%Y-%m")
        cb_key = f"call_minutes:{org_id}:{ym}"
        raw = await self._redis.get(cb_key)
        credit_balance = int(raw) if raw else 0

        remaining: int | None = None
        if usage.allowed_minutes is not None and usage.allowed_minutes > 0:
            remaining = max(0, usage.allowed_minutes - usage.used_minutes)

        return BillingUsageResponse(
            org_id=org_id,
            period=ym,
            used_seconds=usage.used_minutes * 60,
            used_minutes=usage.used_minutes,
            allowed_minutes=usage.allowed_minutes if (usage.allowed_minutes and usage.allowed_minutes > 0) else None,
            remaining_minutes=remaining,
            credit_balance=credit_balance,
            plan_name=plan_name,
        )

    async def get_invoice_preview(self, org_id: UUID) -> InvoicePreviewResponse:
        """
        Estimate the invoice for the current billing period.

        Line items are built from:
        1. Base plan monthly price.
        2. Overage minutes (minutes beyond the plan quota) billed at the
           per-minute rate stored in ``plan.features['overage_rate_usd']``
           (defaults to 0.01 if not set).
        """
        from decimal import ROUND_HALF_UP

        usage_resp = await self.get_usage(org_id)
        sub = await self._sub_repo.get_active(org_id)
        ym = datetime.now(UTC).strftime("%Y-%m")

        line_items: list[InvoiceLineItem] = []
        currency = "USD"
        subtotal = 0.0

        if sub and sub.plan:
            plan = sub.plan
            currency = plan.currency or "USD"
            base_price = float(plan.price_monthly or 0)
            line_items.append(InvoiceLineItem(
                description=f"{plan.name} — base plan (monthly)",
                quantity=1,
                unit_price=base_price,
                amount=base_price,
            ))
            subtotal += base_price

            # Overage
            if (
                usage_resp.allowed_minutes is not None
                and usage_resp.allowed_minutes > 0
                and usage_resp.used_minutes > usage_resp.allowed_minutes
            ):
                overage_mins = usage_resp.used_minutes - usage_resp.allowed_minutes
                features: dict = plan.features or {}
                rate: float = float(features.get("overage_rate_usd", 0.01))
                overage_cost = round(overage_mins * rate, 4)
                line_items.append(InvoiceLineItem(
                    description=f"Overage — {overage_mins} minutes @ ${rate:.4f}/min",
                    quantity=float(overage_mins),
                    unit_price=rate,
                    amount=overage_cost,
                ))
                subtotal += overage_cost
        else:
            line_items.append(InvoiceLineItem(
                description="Free plan — no charge",
                quantity=1,
                unit_price=0.0,
                amount=0.0,
            ))

        return InvoicePreviewResponse(
            org_id=org_id,
            period=ym,
            line_items=line_items,
            subtotal=round(subtotal, 2),
            currency=currency,
            estimated_at=datetime.now(UTC),
        )

    @staticmethod
    def _require_platform_admin(user: User) -> None:
        if not getattr(user, "is_platform_admin", False):
            raise ForbiddenException("Platform admin access required")

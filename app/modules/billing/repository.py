"""
Billing module repositories.

SubscriptionPlanRepository  — plan CRUD + active listing
SubscriptionRepository      — subscription lifecycle queries
InvoiceRepository           — invoice CRUD + paginated listing
PaymentMethodRepository     — payment method management per org
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, UTC
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.models import Invoice, PaymentMethod, Subscription, SubscriptionPlan


# ── SubscriptionPlanRepository ────────────────────────────────────────────

class SubscriptionPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[SubscriptionPlan]:
        result = await self.session.execute(
            select(SubscriptionPlan)
            .where(SubscriptionPlan.is_active.is_(True))
            .order_by(SubscriptionPlan.display_order)
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[SubscriptionPlan]:
        result = await self.session.execute(
            select(SubscriptionPlan).order_by(SubscriptionPlan.display_order)
        )
        return list(result.scalars().all())

    async def get_by_id(self, plan_id: UUID) -> SubscriptionPlan | None:
        result = await self.session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> SubscriptionPlan | None:
        result = await self.session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.slug == slug)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        slug: str,
        description: str | None = None,
        price_monthly: Decimal | None = None,
        price_yearly: Decimal | None = None,
        currency: str = "USD",
        trial_days: int = 0,
        max_seats: int | None = None,
        max_storage_mb: int | None = None,
        display_order: int = 0,
        features: dict | None = None,
    ) -> SubscriptionPlan:
        now = datetime.now(UTC)
        plan = SubscriptionPlan(
            id=_uuid.uuid4(),
            name=name,
            slug=slug,
            description=description,
            price_monthly=price_monthly,
            price_yearly=price_yearly,
            currency=currency,
            trial_days=trial_days,
            max_seats=max_seats,
            max_storage_mb=max_storage_mb,
            is_active=True,
            display_order=display_order,
            features=features or {},
            metadata_={},
            created_at=now,
            updated_at=now,
        )
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def update(self, plan: SubscriptionPlan, **fields) -> SubscriptionPlan:
        for key, val in fields.items():
            if val is not None:
                setattr(plan, key, val)
        plan.updated_at = datetime.now(UTC)
        await self.session.flush()
        return plan

    async def deactivate(self, plan: SubscriptionPlan) -> None:
        plan.is_active = False
        plan.updated_at = datetime.now(UTC)
        await self.session.flush()


# ── SubscriptionRepository ────────────────────────────────────────────────

class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_by_org(self, org_id: UUID) -> Subscription | None:
        """Return the most-recent active or trialing subscription with plan."""
        result = await self.session.execute(
            select(Subscription)
            .where(
                Subscription.organization_id == org_id,
                Subscription.status.in_(list(SubscriptionStatus.ACTIVE_STATUSES)),
            )
            .options(selectinload(Subscription.plan))
            .order_by(Subscription.created_at.desc())
        )
        return result.scalars().first()

    async def get_by_id(self, sub_id: UUID) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.id == sub_id)
            .options(selectinload(Subscription.plan))
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(self, external_id: str) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.external_subscription_id == external_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_org(self, org_id: UUID) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.organization_id == org_id)
            .options(selectinload(Subscription.plan))
            .order_by(Subscription.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        organization_id: UUID,
        plan_id: UUID,
        status: str,
        billing_cycle: str = "monthly",
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
        trial_ends_at: datetime | None = None,
        external_provider: str | None = None,
        external_subscription_id: str | None = None,
        external_customer_id: str | None = None,
        metadata: dict | None = None,
    ) -> Subscription:
        now = datetime.now(UTC)
        sub = Subscription(
            id=_uuid.uuid4(),
            organization_id=organization_id,
            plan_id=plan_id,
            status=status,
            billing_cycle=billing_cycle,
            current_period_start=current_period_start or now,
            current_period_end=current_period_end,
            trial_ends_at=trial_ends_at,
            external_provider=external_provider,
            external_subscription_id=external_subscription_id,
            external_customer_id=external_customer_id,
            metadata_=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self.session.add(sub)
        await self.session.flush()
        return sub

    async def update(self, sub: Subscription, **fields) -> Subscription:
        for key, val in fields.items():
            setattr(sub, key, val)
        sub.updated_at = datetime.now(UTC)
        await self.session.flush()
        return sub


# ── InvoiceRepository ─────────────────────────────────────────────────────

class InvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, invoice_id: UUID, org_id: UUID) -> Invoice | None:
        result = await self.session.execute(
            select(Invoice).where(
                Invoice.id == invoice_id,
                Invoice.organization_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(self, external_id: str) -> Invoice | None:
        result = await self.session.execute(
            select(Invoice).where(Invoice.external_invoice_id == external_id)
        )
        return result.scalar_one_or_none()

    async def list_by_org(
        self, org_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Invoice], int]:
        count_result = await self.session.execute(
            select(func.count()).select_from(Invoice).where(
                Invoice.organization_id == org_id
            )
        )
        total = count_result.scalar_one()
        result = await self.session.execute(
            select(Invoice)
            .where(Invoice.organization_id == org_id)
            .order_by(Invoice.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def create(
        self,
        *,
        organization_id: UUID,
        subscription_id: UUID | None,
        invoice_number: str,
        amount: Decimal,
        currency: str = "USD",
        tax_amount: Decimal | None = None,
        total_amount: Decimal | None = None,
        status: str = "draft",
        due_date: datetime | None = None,
        external_invoice_id: str | None = None,
        billing_details: dict | None = None,
    ) -> Invoice:
        now = datetime.now(UTC)
        tax = tax_amount or Decimal("0")
        total = total_amount or (amount + tax)
        inv = Invoice(
            id=_uuid.uuid4(),
            organization_id=organization_id,
            subscription_id=subscription_id,
            invoice_number=invoice_number,
            amount=amount,
            currency=currency,
            tax_amount=tax,
            total_amount=total,
            status=status,
            due_date=due_date,
            external_invoice_id=external_invoice_id,
            billing_details=billing_details or {},
            created_at=now,
            updated_at=now,
        )
        self.session.add(inv)
        await self.session.flush()
        return inv

    async def update(self, invoice: Invoice, **fields) -> Invoice:
        for key, val in fields.items():
            setattr(invoice, key, val)
        invoice.updated_at = datetime.now(UTC)
        await self.session.flush()
        return invoice

    async def next_invoice_number(self, prefix: str = "INV") -> str:
        today = datetime.now(UTC).strftime("%Y%m%d")
        result = await self.session.execute(
            select(func.count()).select_from(Invoice)
        )
        seq = (result.scalar_one() or 0) + 1
        return f"{prefix}-{today}-{seq:04d}"


# ── PaymentMethodRepository ───────────────────────────────────────────────

class PaymentMethodRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_org(self, org_id: UUID) -> list[PaymentMethod]:
        result = await self.session.execute(
            select(PaymentMethod)
            .where(
                PaymentMethod.organization_id == org_id,
                PaymentMethod.deleted_at.is_(None),
            )
            .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, pm_id: UUID, org_id: UUID) -> PaymentMethod | None:
        result = await self.session.execute(
            select(PaymentMethod).where(
                PaymentMethod.id == pm_id,
                PaymentMethod.organization_id == org_id,
                PaymentMethod.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        organization_id: UUID,
        type: str,
        provider: str | None = None,
        external_payment_method_id: str | None = None,
        last_four: str | None = None,
        card_brand: str | None = None,
        expires_month: int | None = None,
        expires_year: int | None = None,
        billing_address: dict | None = None,
        is_default: bool = False,
    ) -> PaymentMethod:
        now = datetime.now(UTC)
        pm = PaymentMethod(
            id=_uuid.uuid4(),
            organization_id=organization_id,
            type=type,
            provider=provider,
            external_payment_method_id=external_payment_method_id,
            last_four=last_four,
            card_brand=card_brand,
            expires_month=expires_month,
            expires_year=expires_year,
            billing_address=billing_address or {},
            is_default=is_default,
            created_at=now,
            updated_at=now,
        )
        self.session.add(pm)
        await self.session.flush()
        await self.session.refresh(pm)
        return pm

    async def clear_default(self, org_id: UUID) -> None:
        await self.session.execute(
            update(PaymentMethod)
            .where(
                PaymentMethod.organization_id == org_id,
                PaymentMethod.is_default.is_(True),
                PaymentMethod.deleted_at.is_(None),
            )
            .values(is_default=False, updated_at=datetime.now(UTC))
        )

    async def set_default(self, pm: PaymentMethod) -> PaymentMethod:
        await self.clear_default(pm.organization_id)
        pm.is_default = True
        pm.updated_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(pm)
        return pm

    async def soft_delete(self, pm: PaymentMethod) -> None:
        pm.deleted_at = datetime.now(UTC)
        await self.session.flush()

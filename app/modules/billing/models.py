"""
Billing module ORM models.

Tables: subscription_plans, subscriptions, invoices, payment_methods
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    BigInteger,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import SoftDeleteMixin, TimestampMixin


# ── SubscriptionPlan ──────────────────────────────────────────────────────

class SubscriptionPlan(Base, TimestampMixin):
    __tablename__ = "subscription_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    price_monthly: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_yearly: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)

    max_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_storage_mb: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trial_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    features: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="plan", lazy="noload"
    )
    plan_features: Mapped[list["PlanFeature"]] = relationship(
        "PlanFeature", back_populates="plan", cascade="all, delete-orphan", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<SubscriptionPlan slug={self.slug}>"


# ── Subscription ──────────────────────────────────────────────────────────

class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)

    status: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # trialing | active | past_due | canceled | expired
    billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)

    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # External payment provider
    external_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    # Relationships
    plan: Mapped["SubscriptionPlan"] = relationship(
        "SubscriptionPlan", back_populates="subscriptions", lazy="noload"
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice", back_populates="subscription", lazy="noload"
    )

    __table_args__ = (
        Index("ix_subscriptions_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Subscription org={self.organization_id} status={self.status}>"


# ── Invoice ───────────────────────────────────────────────────────────────

class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # draft | pending | paid | failed | refunded
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    external_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    subscription: Mapped["Subscription | None"] = relationship(
        "Subscription", back_populates="invoices", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Invoice number={self.invoice_number} status={self.status}>"


# ── PaymentMethod ─────────────────────────────────────────────────────────

class PaymentMethod(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "payment_methods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # card | bank_account | upi
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_payment_method_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    card_brand: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expires_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    billing_address: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    def __repr__(self) -> str:
        return f"<PaymentMethod type={self.type} org={self.organization_id}>"

"""
Billing module Pydantic schemas.

Plan schemas         — PlanResponse, CreatePlanRequest, UpdatePlanRequest
Subscription schemas — SubscriptionResponse, SubscribeRequest
Invoice schemas      — InvoiceResponse, InvoiceListResponse
Payment methods      — PaymentMethodResponse, AddPaymentMethodRequest
Misc                 — MessageResponse, SubscriptionStatusResponse
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field

from app.shared.base_schemas import CamelModel, PaginationMeta


# ── Plan schemas ──────────────────────────────────────────────────────────

class PlanResponse(CamelModel):
    id: UUID
    name: str
    slug: str
    description: str | None = None
    is_active: bool
    price_monthly: Decimal | None = None
    price_yearly: Decimal | None = None
    currency: str
    trial_days: int
    max_seats: int | None = None
    max_storage_mb: int | None = None
    display_order: int
    features: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CreatePlanRequest(CamelModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: str = Field(..., min_length=2, max_length=100)
    description: str | None = Field(None, max_length=500)
    price_monthly: Decimal | None = Field(None, ge=0)
    price_yearly: Decimal | None = Field(None, ge=0)
    currency: str = Field("USD", max_length=10)
    trial_days: int = Field(0, ge=0, le=365)
    max_seats: int | None = Field(None, ge=1)
    max_storage_mb: int | None = Field(None, ge=1)
    display_order: int = Field(0, ge=0)
    features: dict[str, Any] = Field(default_factory=dict)


class UpdatePlanRequest(CamelModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    description: str | None = None
    price_monthly: Decimal | None = Field(None, ge=0)
    price_yearly: Decimal | None = Field(None, ge=0)
    trial_days: int | None = Field(None, ge=0, le=365)
    max_seats: int | None = None
    max_storage_mb: int | None = None
    display_order: int | None = None
    is_active: bool | None = None
    features: dict[str, Any] | None = None


class PlanListResponse(CamelModel):
    plans: list[PlanResponse]
    total: int


# ── Subscription schemas ──────────────────────────────────────────────────

class SubscriptionPlanBrief(CamelModel):
    id: UUID
    name: str
    slug: str
    price_monthly: Decimal | None = None
    price_yearly: Decimal | None = None
    currency: str


class SubscriptionResponse(CamelModel):
    id: UUID
    organization_id: UUID
    plan: SubscriptionPlanBrief | None = None
    status: str
    billing_cycle: str
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    canceled_at: datetime | None = None
    cancellation_reason: str | None = None
    external_provider: str | None = None
    external_subscription_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SubscribeRequest(CamelModel):
    plan_id: UUID
    billing_cycle: str = Field("monthly", pattern="^(monthly|yearly)$")
    external_customer_id: str | None = None  # If org already has a provider customer


class CancelSubscriptionRequest(CamelModel):
    reason: str | None = Field(None, max_length=500)
    at_period_end: bool = True


class SubscriptionListResponse(CamelModel):
    subscriptions: list[SubscriptionResponse]
    total: int


# ── Invoice schemas ───────────────────────────────────────────────────────

class InvoiceResponse(CamelModel):
    id: UUID
    organization_id: UUID
    subscription_id: UUID | None = None
    invoice_number: str
    amount: Decimal
    currency: str
    tax_amount: Decimal
    total_amount: Decimal
    status: str
    due_date: datetime | None = None
    paid_at: datetime | None = None
    external_invoice_id: str | None = None
    invoice_pdf_url: str | None = None
    billing_details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(CamelModel):
    invoices: list[InvoiceResponse]
    pagination: PaginationMeta


# ── Payment method schemas ────────────────────────────────────────────────

class PaymentMethodResponse(CamelModel):
    id: UUID
    organization_id: UUID
    type: str
    provider: str | None = None
    external_payment_method_id: str | None = None
    is_default: bool
    last_four: str | None = None
    card_brand: str | None = None
    expires_month: int | None = None
    expires_year: int | None = None
    billing_address: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AddPaymentMethodRequest(CamelModel):
    """Attach a pre-created provider payment method to this org."""
    external_payment_method_id: str = Field(..., min_length=1)
    type: str = Field("card", max_length=50)
    provider: str | None = Field(None, max_length=50)
    last_four: str | None = Field(None, min_length=4, max_length=4)
    card_brand: str | None = Field(None, max_length=50)
    expires_month: int | None = Field(None, ge=1, le=12)
    expires_year: int | None = Field(None, ge=2024)
    billing_address: dict[str, Any] = Field(default_factory=dict)
    set_as_default: bool = False


class PaymentMethodListResponse(CamelModel):
    payment_methods: list[PaymentMethodResponse]
    total: int


# ── Webhook ───────────────────────────────────────────────────────────────

class WebhookAckResponse(CamelModel):
    received: bool = True

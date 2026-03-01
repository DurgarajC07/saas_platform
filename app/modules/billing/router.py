"""
Billing module router.

Route prefix (registered in main.py): /api/v1/billing

Endpoints:
  ── Plans (public read / platform-admin write) ──
  GET    /plans                            List active plans (public)
  GET    /plans/{plan_id}                  Plan details (public)
  POST   /plans                            Create plan (admin)
  PATCH  /plans/{plan_id}                  Update plan (admin)
  DELETE /plans/{plan_id}                  Deactivate plan (admin)

  ── Subscriptions (org-scoped) ──
  GET    /subscription                     Current org subscription
  GET    /subscriptions                    All org subscriptions (history)
  POST   /subscribe                        Start / change subscription
  POST   /cancel                           Cancel subscription

  ── Invoices (org-scoped) ──
  GET    /invoices                         Paginated invoice history
  GET    /invoices/{invoice_id}            Invoice detail

  ── Payment methods (org-scoped) ──
  GET    /payment-methods                  List payment methods
  POST   /payment-methods                  Add payment method
  PUT    /payment-methods/{pm_id}/default  Set as default

  ── Webhooks ──
  POST   /webhooks/stripe                  Stripe webhook receiver
  POST   /webhooks/razorpay               Razorpay webhook receiver (stub)
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.core.exceptions import BadRequestException
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.billing.schemas import (
    AddPaymentMethodRequest,
    CancelSubscriptionRequest,
    CreatePlanRequest,
    InvoiceListResponse,
    InvoiceResponse,
    PaymentMethodListResponse,
    PaymentMethodResponse,
    PlanListResponse,
    PlanResponse,
    SubscribeRequest,
    SubscriptionListResponse,
    SubscriptionResponse,
    UpdatePlanRequest,
    WebhookAckResponse,
)
from app.modules.billing.service import BillingService
from app.modules.rbac.dependencies import get_current_org_id
from app.shared.base_schemas import CamelModel
import redis.asyncio as aioredis

router = APIRouter()

# ── Type aliases ──────────────────────────────────────────────────────────
CurrentUser = Annotated[User, Depends(get_current_user)]
OrgID       = Annotated[UUID, Depends(get_current_org_id)]
DB          = Annotated[AsyncSession, Depends(get_db)]
Redis       = Annotated[aioredis.Redis, Depends(get_redis)]


def _billing(db: AsyncSession, redis: aioredis.Redis) -> BillingService:
    return BillingService(db, redis)


class MessageResponse(CamelModel):
    message: str = "Success"


# ═══════════════════════════════════════════════════════════════════════════
# Plans — public read
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/plans",
    response_model=PlanListResponse,
    summary="List all active subscription plans",
)
async def list_plans(db: DB, redis: Redis) -> PlanListResponse:
    """Public endpoint — no auth required."""
    return await _billing(db, redis).list_plans()


@router.get(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    summary="Get subscription plan details",
)
async def get_plan(plan_id: UUID, db: DB, redis: Redis) -> PlanResponse:
    return await _billing(db, redis).get_plan(plan_id)


# ── Plans — admin write ───────────────────────────────────────────────────

@router.post(
    "/plans",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subscription plan (platform admin only)",
)
async def create_plan(
    data: CreatePlanRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> PlanResponse:
    return await _billing(db, redis).create_plan(data, user, request)


@router.patch(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    summary="Update a subscription plan (platform admin only)",
)
async def update_plan(
    plan_id: UUID,
    data: UpdatePlanRequest,
    request: Request,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> PlanResponse:
    return await _billing(db, redis).update_plan(plan_id, data, user, request)


@router.delete(
    "/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a subscription plan (platform admin only)",
)
async def delete_plan(
    plan_id: UUID,
    request: Request,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> None:
    await _billing(db, redis).delete_plan(plan_id, user, request)


# ═══════════════════════════════════════════════════════════════════════════
# Subscriptions
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/subscription",
    response_model=SubscriptionResponse | None,
    summary="Get current org subscription status",
)
async def get_subscription(
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> SubscriptionResponse | None:
    return await _billing(db, redis).get_subscription(org_id)


@router.get(
    "/subscriptions",
    response_model=SubscriptionListResponse,
    summary="List all historical subscriptions for the org",
)
async def list_subscriptions(
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> SubscriptionListResponse:
    return await _billing(db, redis).list_subscriptions(org_id)


@router.post(
    "/subscribe",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start or change the org subscription",
)
async def subscribe(
    data: SubscribeRequest,
    request: Request,
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> SubscriptionResponse:
    return await _billing(db, redis).subscribe(org_id, data, user, request)


@router.post(
    "/cancel",
    response_model=SubscriptionResponse,
    summary="Cancel the active subscription",
)
async def cancel_subscription(
    data: CancelSubscriptionRequest,
    request: Request,
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> SubscriptionResponse:
    return await _billing(db, redis).cancel_subscription(org_id, data, user, request)


# ═══════════════════════════════════════════════════════════════════════════
# Invoices
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/invoices",
    response_model=InvoiceListResponse,
    summary="Paginated invoice history for the org",
)
async def list_invoices(
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
    page: int = 1,
    page_size: int = 20,
) -> InvoiceListResponse:
    return await _billing(db, redis).list_invoices(org_id, page=page, page_size=page_size)


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Get invoice detail",
)
async def get_invoice(
    invoice_id: UUID,
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> InvoiceResponse:
    return await _billing(db, redis).get_invoice(invoice_id, org_id)


# ═══════════════════════════════════════════════════════════════════════════
# Payment Methods
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/payment-methods",
    response_model=PaymentMethodListResponse,
    summary="List payment methods for the org",
)
async def list_payment_methods(
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> PaymentMethodListResponse:
    return await _billing(db, redis).list_payment_methods(org_id)


@router.post(
    "/payment-methods",
    response_model=PaymentMethodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a payment method to the org",
)
async def add_payment_method(
    data: AddPaymentMethodRequest,
    request: Request,
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> PaymentMethodResponse:
    return await _billing(db, redis).add_payment_method(org_id, data, user, request)


@router.put(
    "/payment-methods/{pm_id}/default",
    response_model=PaymentMethodResponse,
    summary="Set a payment method as the default",
)
async def set_default_payment_method(
    pm_id: UUID,
    request: Request,
    user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> PaymentMethodResponse:
    return await _billing(db, redis).set_default_payment_method(pm_id, org_id, user, request)


# ═══════════════════════════════════════════════════════════════════════════
# Webhooks
# ═══════════════════════════════════════════════════════════════════════════

@router.post(
    "/webhooks/stripe",
    response_model=WebhookAckResponse,
    summary="Stripe webhook receiver",
    include_in_schema=False,  # Don't expose to OpenAPI docs
)
async def stripe_webhook(
    request: Request,
    db: DB,
    redis: Redis,
    stripe_signature: str | None = Header(None, alias="stripe-signature"),
) -> WebhookAckResponse:
    """
    Verify the Stripe-Signature header and dispatch to the appropriate
    event handler.  Always returns 200 to acknowledge receipt — Stripe
    will retry on non-2xx responses.
    """
    from app.modules.billing.providers import get_provider
    payload = await request.body()
    provider = get_provider()

    try:
        event = provider.verify_webhook(payload, stripe_signature or "")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {exc}")

    svc = BillingService(db, redis, provider)
    await svc.handle_stripe_webhook(
        event_type=event.get("type", ""),
        data=event.get("data", {}),
    )
    return WebhookAckResponse(received=True)


@router.post(
    "/webhooks/razorpay",
    response_model=WebhookAckResponse,
    summary="Razorpay webhook receiver (stub)",
    include_in_schema=False,
)
async def razorpay_webhook(request: Request) -> WebhookAckResponse:
    """
    Razorpay webhook stub — signature verification and event routing
    are not yet implemented.  Returns 200 to prevent Razorpay retries.
    """
    return WebhookAckResponse(received=True)

"""
Billing module constants.

Central place for status strings, cache keys, and billing-cycle definitions
so they can be imported uniformly across service, repository, and router.
"""

from __future__ import annotations
from uuid import UUID

# ── Subscription statuses ─────────────────────────────────────────────────
class SubscriptionStatus:
    TRIALING  = "trialing"
    ACTIVE    = "active"
    PAST_DUE  = "past_due"
    CANCELED  = "canceled"
    EXPIRED   = "expired"
    INCOMPLETE = "incomplete"

    ACTIVE_STATUSES = {"trialing", "active"}

# ── Invoice statuses ──────────────────────────────────────────────────────
class InvoiceStatus:
    DRAFT   = "draft"
    PENDING = "pending"
    PAID    = "paid"
    FAILED  = "failed"
    REFUNDED = "refunded"

# ── Billing cycles ────────────────────────────────────────────────────────
class BillingCycle:
    MONTHLY = "monthly"
    YEARLY  = "yearly"
    ALL = {MONTHLY, YEARLY}

# ── Payment method types ──────────────────────────────────────────────────
class PaymentMethodType:
    CARD         = "card"
    BANK_ACCOUNT = "bank_account"
    UPI          = "upi"

# ── Redis cache key patterns ──────────────────────────────────────────────
SUBSCRIPTION_CACHE_PREFIX = "sub"

def subscription_cache_key(org_id: UUID) -> str:
    return f"{SUBSCRIPTION_CACHE_PREFIX}:{org_id}"

# ── Stripe webhook event types ────────────────────────────────────────────
class StripeEvent:
    INVOICE_PAID               = "invoice.paid"
    INVOICE_PAYMENT_FAILED     = "invoice.payment_failed"
    SUBSCRIPTION_DELETED       = "customer.subscription.deleted"
    SUBSCRIPTION_UPDATED       = "customer.subscription.updated"
    CUSTOMER_CREATED           = "customer.created"

# ── Invoice number prefix ─────────────────────────────────────────────────
INVOICE_NUMBER_PREFIX = "INV"

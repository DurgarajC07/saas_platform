"""
Stripe payment provider adapter.

Uses the synchronous Stripe Python SDK wrapped in ``asyncio.to_thread``
for every I/O operation so it fits cleanly into the async service layer.
All network calls are made in the default thread-pool executor.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import stripe as _stripe

from app.modules.billing.providers.base import PaymentProviderBase


class StripeProvider(PaymentProviderBase):
    def __init__(self, *, api_key: str, webhook_secret: str) -> None:
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        # Set on the module so all SDK calls within this process use our key.
        # In a multi-key scenario this should use StripeClient instead.
        if api_key:
            _stripe.api_key = api_key

    # ── Customers ─────────────────────────────────────────────────────────

    async def create_customer(
        self,
        org_id: UUID,
        org_name: str,
        email: str | None = None,
    ) -> str:
        params: dict = {
            "name": org_name,
            "metadata": {"org_id": str(org_id)},
        }
        if email:
            params["email"] = email

        customer = await asyncio.to_thread(
            _stripe.Customer.create, **params
        )
        return customer.id  # type: ignore[attr-defined]

    async def get_customer(self, customer_id: str) -> dict:
        customer = await asyncio.to_thread(
            _stripe.Customer.retrieve, customer_id
        )
        return dict(customer)  # type: ignore[arg-type]

    # ── Subscriptions ─────────────────────────────────────────────────────

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> dict:
        params: dict = {
            "customer": customer_id,
            "items": [{"price": price_id}],
            "metadata": metadata or {},
        }
        if trial_days > 0:
            params["trial_period_days"] = trial_days

        sub = await asyncio.to_thread(
            _stripe.Subscription.create, **params
        )
        return {
            "id": sub.id,
            "status": sub.status,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "trial_end": getattr(sub, "trial_end", None),
        }

    async def cancel_subscription(
        self,
        subscription_id: str,
        *,
        at_period_end: bool = True,
    ) -> dict:
        sub = await asyncio.to_thread(
            _stripe.Subscription.modify,
            subscription_id,
            cancel_at_period_end=at_period_end,
        )
        return {"id": sub.id, "status": sub.status, "cancel_at_period_end": sub.cancel_at_period_end}

    async def get_subscription(self, subscription_id: str) -> dict:
        sub = await asyncio.to_thread(
            _stripe.Subscription.retrieve, subscription_id
        )
        return {"id": sub.id, "status": sub.status}

    # ── Checkout sessions ─────────────────────────────────────────────────

    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> str:
        params: dict = {
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata or {},
        }
        if trial_days > 0:
            params["subscription_data"] = {"trial_period_days": trial_days}

        session = await asyncio.to_thread(
            _stripe.checkout.Session.create, **params
        )
        return session.url  # type: ignore[attr-defined]

    # ── Webhooks ──────────────────────────────────────────────────────────

    def verify_webhook(self, payload: bytes, signature: str) -> dict:
        """
        Verify the Stripe-Signature header and return the parsed event dict.
        Raises ``stripe.error.SignatureVerificationError`` on failure.
        """
        if not self._webhook_secret:
            # Dev/test mode — skip verification, parse raw JSON
            import json
            return json.loads(payload)

        event = _stripe.Webhook.construct_event(
            payload, signature, self._webhook_secret
        )
        return dict(event)

    # ── Payment methods ───────────────────────────────────────────────────

    async def attach_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> dict:
        pm = await asyncio.to_thread(
            _stripe.PaymentMethod.attach,
            payment_method_id,
            customer=customer_id,
        )
        return {
            "id": pm.id,
            "type": pm.type,
            "card": dict(pm.card) if pm.type == "card" and pm.card else {},
        }

    async def list_payment_methods(
        self,
        customer_id: str,
        method_type: str = "card",
    ) -> list[dict]:
        result = await asyncio.to_thread(
            _stripe.PaymentMethod.list,
            customer=customer_id,
            type=method_type,
        )
        return [
            {
                "id": pm.id,
                "type": pm.type,
                "card": dict(pm.card) if pm.type == "card" and pm.card else {},
            }
            for pm in result.data
        ]

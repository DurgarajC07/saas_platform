"""
Razorpay payment provider adapter — interface stub.

The full implementation is outside the scope of Day 7 deliverables.
All methods raise ``NotImplementedError`` so the application won't silently
use this adapter in production before it's wired up.
"""

from __future__ import annotations

from uuid import UUID

from app.modules.billing.providers.base import PaymentProviderBase


class RazorpayProvider(PaymentProviderBase):
    def __init__(self, *, key_id: str, key_secret: str) -> None:
        self._key_id = key_id
        self._key_secret = key_secret

    async def create_customer(self, org_id: UUID, org_name: str, email: str | None = None) -> str:
        raise NotImplementedError("RazorpayProvider.create_customer not yet implemented")

    async def get_customer(self, customer_id: str) -> dict:
        raise NotImplementedError("RazorpayProvider.get_customer not yet implemented")

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> dict:
        raise NotImplementedError("RazorpayProvider.create_subscription not yet implemented")

    async def cancel_subscription(
        self,
        subscription_id: str,
        *,
        at_period_end: bool = True,
    ) -> dict:
        raise NotImplementedError("RazorpayProvider.cancel_subscription not yet implemented")

    async def get_subscription(self, subscription_id: str) -> dict:
        raise NotImplementedError("RazorpayProvider.get_subscription not yet implemented")

    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> str:
        raise NotImplementedError("RazorpayProvider.create_checkout_session not yet implemented")

    def verify_webhook(self, payload: bytes, signature: str) -> dict:
        raise NotImplementedError("RazorpayProvider.verify_webhook not yet implemented")

    async def attach_payment_method(self, customer_id: str, payment_method_id: str) -> dict:
        raise NotImplementedError("RazorpayProvider.attach_payment_method not yet implemented")

    async def list_payment_methods(self, customer_id: str, method_type: str = "card") -> list[dict]:
        raise NotImplementedError("RazorpayProvider.list_payment_methods not yet implemented")

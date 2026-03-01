"""
Abstract base class for all payment provider adapters.

Concrete implementations (StripeProvider, RazorpayProvider) must
implement every abstract method.  All methods are async to keep the
interface uniform even when the underlying SDK is synchronous — sync
calls must be wrapped via ``asyncio.to_thread``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class PaymentProviderBase(ABC):
    """Uniform interface for external payment processors."""

    # ── Customer management ───────────────────────────────────────────────

    @abstractmethod
    async def create_customer(
        self,
        org_id: UUID,
        org_name: str,
        email: str | None = None,
    ) -> str:
        """
        Create a customer record in the provider and return the external
        customer ID string (e.g. Stripe ``cus_…``).
        """
        ...

    @abstractmethod
    async def get_customer(self, customer_id: str) -> dict:
        """Fetch customer details from the provider."""
        ...

    # ── Subscriptions ─────────────────────────────────────────────────────

    @abstractmethod
    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> dict:
        """
        Create a subscription in the provider.
        Returns a dict with at minimum:
          - ``id``     : external subscription ID
          - ``status`` : provider status string
        """
        ...

    @abstractmethod
    async def cancel_subscription(
        self,
        subscription_id: str,
        *,
        at_period_end: bool = True,
    ) -> dict:
        """
        Cancel a subscription.
        ``at_period_end=True`` schedules cancellation at the billing period end.
        Returns updated subscription dict.
        """
        ...

    @abstractmethod
    async def get_subscription(self, subscription_id: str) -> dict:
        """Fetch subscription details from the provider."""
        ...

    # ── Checkout sessions ─────────────────────────────────────────────────

    @abstractmethod
    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> str:
        """
        Create a hosted checkout session.
        Returns the session URL string.
        """
        ...

    # ── Webhook verification ──────────────────────────────────────────────

    @abstractmethod
    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> dict:
        """
        Verify the webhook signature and parse the event payload.
        Raises ValueError on invalid / tampered signatures.
        Returns the parsed event dict.
        """
        ...

    # ── Payment methods ───────────────────────────────────────────────────

    @abstractmethod
    async def attach_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> dict:
        """Attach a payment method to a customer."""
        ...

    @abstractmethod
    async def list_payment_methods(
        self,
        customer_id: str,
        method_type: str = "card",
    ) -> list[dict]:
        """List payment methods attached to a customer."""
        ...

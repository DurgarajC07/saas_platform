"""
Billing providers package.

Base abstract class + concrete adapters for Stripe and Razorpay.
Import the factory ``get_provider()`` to get the configured provider.
"""
from __future__ import annotations

from app.modules.billing.providers.base import PaymentProviderBase
from app.modules.billing.providers.stripe_provider import StripeProvider
from app.modules.billing.providers.razorpay_provider import RazorpayProvider


def get_provider(settings=None) -> PaymentProviderBase:
    """
    Return the active payment provider adapter based on BILLING_PROVIDER setting.
    Can be called lazily — settings are fetched if not supplied.
    """
    from app.config import get_settings
    s = settings or get_settings()
    provider = s.BILLING_PROVIDER.lower()

    if provider == "stripe":
        return StripeProvider(api_key=s.STRIPE_SECRET_KEY, webhook_secret=s.STRIPE_WEBHOOK_SECRET)
    if provider == "razorpay":
        return RazorpayProvider(key_id=s.RAZORPAY_KEY_ID, key_secret=s.RAZORPAY_KEY_SECRET)

    # Fallback: noop provider (for dev/test with no credentials)
    return StripeProvider(api_key="", webhook_secret="")


__all__ = ["PaymentProviderBase", "StripeProvider", "RazorpayProvider", "get_provider"]

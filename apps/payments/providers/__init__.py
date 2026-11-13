from django.conf import settings

from .base import (
    InvalidSignature,
    PaymentProvider,
    ProviderError,
    ProviderNotConfigured,
)
from .flutterwave import FlutterwaveProvider
from .sandbox import SandboxProvider

REGISTRY = {p.code: p for p in (SandboxProvider, FlutterwaveProvider)}


def get_provider(code) -> PaymentProvider:
    if code not in REGISTRY or code not in settings.PAYMENT_PROVIDERS_ENABLED:
        raise ProviderNotConfigured(f"Payment provider '{code}' is not enabled.")
    return REGISTRY[code]()


def available_providers():
    """Providers a customer can choose at checkout (enabled and configured)."""
    out = []
    for code in settings.PAYMENT_PROVIDERS_ENABLED:
        cls = REGISTRY.get(code)
        if cls and cls().is_configured():
            out.append(cls())
    return out


__all__ = ["get_provider", "available_providers", "InvalidSignature", "ProviderError", "ProviderNotConfigured", "PaymentProvider"]

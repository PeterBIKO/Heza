from dataclasses import dataclass, field
from decimal import Decimal


class ProviderError(Exception):
    """The provider rejected a request or could not be reached."""


class ProviderNotConfigured(ProviderError):
    pass


class InvalidSignature(Exception):
    """Webhook failed authenticity checks. Never process its payload."""


@dataclass
class InitResult:
    checkout_url: str
    provider_reference: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class VerifyResult:
    status: str  # "successful" | "failed" | "pending"
    amount: Decimal
    currency: str
    tx_ref: str
    provider_transaction_id: str = ""
    method: str = ""
    raw: dict = field(default_factory=dict)
    failure_reason: str = ""


@dataclass
class WebhookResult:
    event_id: str
    tx_ref: str
    provider_transaction_id: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class RefundResult:
    status: str  # "succeeded" | "processing" | "failed"
    provider_refund_id: str = ""
    raw: dict = field(default_factory=dict)
    failure_reason: str = ""


class PaymentProvider:
    """Contract every gateway adapter implements.

    The app never treats a browser redirect or a webhook body as proof of payment. A webhook is
    first authenticated (parse_webhook), then the transaction is re-fetched server-to-server
    (verify) and only that result moves money and confirms bookings.
    """

    code = ""
    label = ""
    supports_refunds = True

    def is_configured(self):
        return True

    def initiate(self, payment, *, customer, redirect_url, base_url) -> InitResult:
        raise NotImplementedError

    def verify(self, payment, provider_transaction_id="") -> VerifyResult:
        raise NotImplementedError

    def parse_webhook(self, body: bytes, headers) -> WebhookResult:
        raise NotImplementedError

    def refund(self, payment, amount) -> RefundResult:
        raise NotImplementedError

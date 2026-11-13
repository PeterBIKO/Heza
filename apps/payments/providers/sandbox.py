"""Local sandbox gateway.

Behaves like an external provider: it owns its own transaction table (SandboxTransaction), hosts a
checkout page, and notifies Heza through HMAC-SHA256 signed webhooks with a timestamp to block replays.
Enable only in development/staging (PAYMENT_PROVIDERS_ENABLED).
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal

from django.conf import settings
from django.urls import reverse

from .base import (
    InitResult,
    InvalidSignature,
    PaymentProvider,
    RefundResult,
    VerifyResult,
    WebhookResult,
)

SIGNATURE_HEADER = "HTTP_X_HEZA_SANDBOX_SIGNATURE"
TOLERANCE_SECONDS = 300


def sign(body: bytes, secret=None, timestamp=None):
    secret = (secret or settings.SANDBOX_WEBHOOK_SECRET).encode()
    timestamp = int(timestamp or time.time())
    digest = hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_signature(body: bytes, header: str, secret=None, now=None):
    if not header:
        raise InvalidSignature("missing signature header")
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        received = parts["v1"]
    except (KeyError, ValueError) as exc:
        raise InvalidSignature("malformed signature header") from exc
    now = now or time.time()
    if abs(now - timestamp) > TOLERANCE_SECONDS:
        raise InvalidSignature("signature timestamp outside tolerance")
    expected = sign(body, secret, timestamp).split("v1=")[1]
    if not hmac.compare_digest(expected, received):
        raise InvalidSignature("signature mismatch")
    return True


class SandboxProvider(PaymentProvider):
    code = "sandbox"
    label = "Heza Sandbox (test card / test MoMo)"

    def initiate(self, payment, *, customer, redirect_url, base_url):
        from apps.payments.models import SandboxTransaction

        txn, _ = SandboxTransaction.objects.get_or_create(
            tx_ref=payment.reference,
            defaults={
                "amount": payment.amount, "currency": payment.currency,
                "customer_email": customer.email, "redirect_url": redirect_url,
            },
        )
        url = base_url.rstrip("/") + reverse("payments:sandbox_checkout", args=[txn.txn_id])
        return InitResult(checkout_url=url, provider_reference=txn.txn_id, raw={"txn_id": txn.txn_id})

    def verify(self, payment, provider_transaction_id=""):
        from apps.payments.models import SandboxTransaction

        txn = SandboxTransaction.objects.filter(tx_ref=payment.reference).first()
        if txn is None:
            return VerifyResult(status="failed", amount=Decimal("0"), currency=payment.currency, tx_ref=payment.reference,
                                failure_reason="unknown transaction")
        return VerifyResult(
            status=txn.status if txn.status != "pending" else "pending",
            amount=txn.amount, currency=txn.currency, tx_ref=txn.tx_ref, provider_transaction_id=txn.txn_id,
            method=txn.method, raw={"txn_id": txn.txn_id, "status": txn.status, "amount": str(txn.amount)},
            failure_reason="declined in sandbox" if txn.status == "failed" else "",
        )

    def parse_webhook(self, body, headers):
        verify_signature(body, headers.get(SIGNATURE_HEADER, ""))
        try:
            data = json.loads(body)
            return WebhookResult(event_id=data["id"], tx_ref=data["data"]["tx_ref"], provider_transaction_id=data["data"]["txn_id"], raw=data)
        except (ValueError, KeyError) as exc:
            raise InvalidSignature("malformed payload") from exc

    def refund(self, payment, amount):
        from apps.payments.models import SandboxTransaction

        txn = SandboxTransaction.objects.filter(tx_ref=payment.reference, status="successful").first()
        if txn is None or txn.refunded_amount + amount > txn.amount:
            return RefundResult(status="failed", failure_reason="refund exceeds captured amount")
        txn.refunded_amount += amount
        txn.save(update_fields=["refunded_amount"])
        return RefundResult(status="succeeded", provider_refund_id=f"RF-{txn.txn_id}-{int(txn.refunded_amount)}")


def build_webhook_body(txn, event_id):
    return json.dumps(
        {"id": event_id, "type": "charge.completed", "data": {"tx_ref": txn.tx_ref, "txn_id": txn.txn_id, "status": txn.status,
                                                               "amount": str(txn.amount), "currency": txn.currency}},
        separators=(",", ":"),
    ).encode()

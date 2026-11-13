"""Flutterwave v3 adapter (cards + Rwanda mobile money).

Docs: https://developer.flutterwave.com/docs — Standard checkout (/payments), transaction verify,
webhooks authenticated by the `verif-hash` header that must equal the secret hash set in the dashboard.
"""
import hmac
import json
import logging
from decimal import Decimal

import requests
from django.conf import settings

from .base import (
    InitResult,
    InvalidSignature,
    PaymentProvider,
    ProviderError,
    ProviderNotConfigured,
    RefundResult,
    VerifyResult,
    WebhookResult,
)

log = logging.getLogger(__name__)
TIMEOUT = 20
SAFE_KEYS = {"id", "tx_ref", "flw_ref", "status", "amount", "charged_amount", "currency", "payment_type", "created_at", "processor_response"}


def _sanitise(data):
    """Keep only non-sensitive fields. Card details never reach Heza (hosted checkout), but be strict anyway."""
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in SAFE_KEYS}


class FlutterwaveProvider(PaymentProvider):
    code = "flutterwave"
    label = "Card or MTN/Airtel Mobile Money (Flutterwave)"

    def is_configured(self):
        return bool(settings.FLUTTERWAVE_SECRET_KEY and settings.FLUTTERWAVE_SECRET_HASH)

    def _headers(self):
        if not self.is_configured():
            raise ProviderNotConfigured("Set FLUTTERWAVE_SECRET_KEY and FLUTTERWAVE_SECRET_HASH to enable Flutterwave.")
        return {"Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}", "Content-Type": "application/json"}

    def _request(self, method, path, **kwargs):
        url = settings.FLUTTERWAVE_BASE_URL.rstrip("/") + path
        try:
            resp = requests.request(method, url, headers=self._headers(), timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise ProviderError(f"Flutterwave unreachable: {exc}") from exc
        try:
            body = resp.json()
        except ValueError as exc:
            raise ProviderError(f"Flutterwave returned non-JSON ({resp.status_code})") from exc
        if resp.status_code >= 400 or body.get("status") != "success":
            raise ProviderError(body.get("message") or f"Flutterwave error {resp.status_code}")
        return body

    def initiate(self, payment, *, customer, redirect_url, base_url):
        booking = payment.booking
        payload = {
            "tx_ref": payment.reference,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "redirect_url": redirect_url,
            "payment_options": "card,mobilemoneyrwanda",
            "customer": {"email": customer.email, "name": booking.guest_name, "phonenumber": booking.guest_phone},
            "customizations": {"title": "Heza", "description": f"Booking {booking.reference} · {booking.property.name}"},
            "meta": {"booking_reference": booking.reference},
        }
        body = self._request("POST", "/payments", data=json.dumps(payload))
        return InitResult(checkout_url=body["data"]["link"], raw={"status": body.get("status")})

    def verify(self, payment, provider_transaction_id=""):
        if provider_transaction_id and str(provider_transaction_id).isdigit():
            body = self._request("GET", f"/transactions/{provider_transaction_id}/verify")
        else:
            body = self._request("GET", "/transactions/verify_by_reference", params={"tx_ref": payment.reference})
        data = body.get("data") or {}
        status = data.get("status", "pending")
        status = {"successful": "successful", "failed": "failed", "cancelled": "failed"}.get(status, "pending")
        return VerifyResult(
            status=status,
            amount=Decimal(str(data.get("amount", "0"))),
            currency=data.get("currency", ""),
            tx_ref=data.get("tx_ref", ""),
            provider_transaction_id=str(data.get("id", "")),
            method=data.get("payment_type", ""),
            raw=_sanitise(data),
            failure_reason=data.get("processor_response", "") if status == "failed" else "",
        )

    def parse_webhook(self, body, headers):
        expected = settings.FLUTTERWAVE_SECRET_HASH
        received = headers.get("HTTP_VERIF_HASH", "")
        if not expected or not received or not hmac.compare_digest(expected, received):
            raise InvalidSignature("verif-hash mismatch")
        try:
            payload = json.loads(body)
            data = payload.get("data") or {}
            return WebhookResult(
                event_id=f"{payload.get('event', 'event')}:{data['id']}",
                tx_ref=data["tx_ref"],
                provider_transaction_id=str(data["id"]),
                raw={"event": payload.get("event"), "data": _sanitise(data)},
            )
        except (ValueError, KeyError, AttributeError) as exc:
            raise InvalidSignature("malformed payload") from exc

    def refund(self, payment, amount):
        if not payment.provider_transaction_id:
            return RefundResult(status="failed", failure_reason="missing transaction id")
        try:
            body = self._request("POST", f"/transactions/{payment.provider_transaction_id}/refund", data=json.dumps({"amount": str(amount)}))
        except ProviderError as exc:
            return RefundResult(status="failed", failure_reason=str(exc)[:250])
        data = body.get("data") or {}
        status = "succeeded" if str(data.get("status", "")).lower() in {"completed", "successful"} else "processing"
        return RefundResult(status=status, provider_refund_id=str(data.get("id", "")), raw=_sanitise(data))

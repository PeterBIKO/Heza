import json
import time
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.bookings import services as bs
from apps.bookings.models import Booking
from apps.core.testing import days, make_property, make_room, make_user

from . import services as pay
from .models import (
    LedgerEntry,
    Payment,
    Payout,
    Refund,
    SandboxTransaction,
    WebhookEvent,
)
from .providers.base import InvalidSignature
from .providers.sandbox import build_webhook_body, sign, verify_signature

SANDBOX = {"PAYMENT_PROVIDERS_ENABLED": ["sandbox", "flutterwave"], "SANDBOX_WEBHOOK_SECRET": "test-secret",
           "FLUTTERWAVE_SECRET_HASH": "fw-hash", "RATELIMIT_ENABLED": False}


def new_booking(customer=None, price=100000, pay_later=False, **prop_kw):
    customer = customer or make_user()
    room = make_room(prop=make_property(**prop_kw), price=price, quantity=3)
    return bs.create_room_booking(customer=customer, room_type_id=room.pk, check_in=days(20), check_out=days(22), rooms=1,
                                  adults=1, children=0, guest=bs.GuestDetails("G", customer.email, "+250788000000", ""), pay_later=pay_later)


def start(booking, option="full"):
    return pay.start_payment(booking, option=option, provider_code="sandbox", customer=booking.customer, base_url="http://testserver")


def gateway_settles(payment, status="successful", amount=None):
    txn = SandboxTransaction.objects.get(tx_ref=payment.reference)
    txn.status = status
    if amount is not None:
        txn.amount = Decimal(amount)
    txn.save()
    return txn


def post_webhook(client, txn, event_id="evt_1", secret="test-secret", body=None, timestamp=None):
    body = body or build_webhook_body(txn, event_id)
    return client.post(reverse("payments:webhook", args=["sandbox"]), data=body, content_type="application/json",
                       HTTP_X_HEZA_SANDBOX_SIGNATURE=sign(body, secret, timestamp))


@override_settings(**SANDBOX)
class SignatureTests(TestCase):
    def test_valid_signature(self):
        body = b'{"a":1}'
        self.assertTrue(verify_signature(body, sign(body)))

    def test_tampered_body_rejected(self):
        header = sign(b'{"a":1}')
        with self.assertRaises(InvalidSignature):
            verify_signature(b'{"a":2}', header)

    def test_wrong_secret_rejected(self):
        body = b"{}"
        with self.assertRaises(InvalidSignature):
            verify_signature(body, sign(body, secret="other"))

    def test_replay_outside_tolerance_rejected(self):
        body = b"{}"
        with self.assertRaises(InvalidSignature):
            verify_signature(body, sign(body, timestamp=time.time() - 3600))

    def test_missing_or_malformed_header(self):
        for header in ("", "garbage", "t=abc,v1=x"):
            with self.assertRaises(InvalidSignature):
                verify_signature(b"{}", header)


@override_settings(**SANDBOX)
class WebhookFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.booking = new_booking()
        self.payment = start(self.booking)

    def test_signed_webhook_confirms_after_server_verification(self):
        txn = gateway_settles(self.payment)
        r = post_webhook(self.client, txn)
        self.assertEqual(r.status_code, 200)
        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCESSFUL)
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertEqual(self.booking.amount_paid, self.booking.total)

    def test_invalid_signature_is_rejected_and_logged(self):
        txn = gateway_settles(self.payment)
        r = post_webhook(self.client, txn, secret="attacker")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(WebhookEvent.objects.filter(signature_valid=False).exists())
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.PENDING)

    def test_forged_success_body_does_not_confirm_when_gateway_says_pending(self):
        """Even a correctly signed 'successful' body only triggers a verify; the gateway's record decides."""
        txn = SandboxTransaction.objects.get(tx_ref=self.payment.reference)
        body = json.dumps({"id": "evt_forged", "data": {"tx_ref": txn.tx_ref, "txn_id": txn.txn_id, "status": "successful"}}).encode()
        post_webhook(self.client, txn, body=body)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).status, Booking.Status.PENDING)

    def test_amount_mismatch_fails_payment(self):
        txn = gateway_settles(self.payment, amount=self.payment.amount - 1)
        post_webhook(self.client, txn)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertIn("amount mismatch", self.payment.failure_reason)
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).amount_paid, 0)

    def test_duplicate_webhooks_credit_once(self):
        txn = gateway_settles(self.payment)
        post_webhook(self.client, txn, event_id="evt_same")
        post_webhook(self.client, txn, event_id="evt_same")
        post_webhook(self.client, txn, event_id="evt_other")
        self.assertEqual(LedgerEntry.objects.filter(payment=self.payment, entry_type="booking_income").count(), 1)
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).amount_paid, self.payment.amount)

    def test_declined_payment_leaves_booking_pending(self):
        txn = gateway_settles(self.payment, status="failed")
        post_webhook(self.client, txn)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).status, Booking.Status.PENDING)

    def test_return_url_never_trusts_query_string(self):
        self.client.force_login(self.booking.customer)
        r = self.client.get(reverse("payments:return", args=[self.payment.reference]) + "?status=successful")
        self.assertEqual(r.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_return_url_is_private_to_the_customer(self):
        self.client.force_login(make_user())
        r = self.client.get(reverse("payments:return", args=[self.payment.reference]))
        self.assertEqual(r.status_code, 404)

    def test_flutterwave_webhook_requires_verif_hash(self):
        body = json.dumps({"event": "charge.completed", "data": {"id": 1, "tx_ref": self.payment.reference}}).encode()
        r = self.client.post(reverse("payments:webhook", args=["flutterwave"]), data=body, content_type="application/json", HTTP_VERIF_HASH="wrong")
        self.assertEqual(r.status_code, 401)

    def test_sandbox_checkout_end_to_end(self):
        txn = SandboxTransaction.objects.get(tx_ref=self.payment.reference)
        r = self.client.post(reverse("payments:sandbox_checkout", args=[txn.txn_id]), {"action": "approve", "method": "card"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).status, Booking.Status.CONFIRMED)

    @override_settings(PAYMENT_PROVIDERS_ENABLED=["flutterwave"])
    def test_sandbox_disabled_in_production_config(self):
        txn = SandboxTransaction.objects.get(tx_ref=self.payment.reference)
        self.assertEqual(self.client.get(reverse("payments:sandbox_checkout", args=[txn.txn_id])).status_code, 404)
        r = post_webhook(self.client, txn)
        self.assertEqual(r.status_code, 404)


@override_settings(**SANDBOX)
class LedgerTests(TestCase):
    def setUp(self):
        cache.clear()

    def paid_booking(self, **kw):
        booking = new_booking(**kw)
        payment = start(booking)
        gateway_settles(payment)
        pay.verify_payment(payment)
        booking.refresh_from_db()
        return booking, payment

    def test_commission_split_on_payment(self):
        booking, payment = self.paid_booking()
        vendor_wallet = pay.get_wallet(booking.vendor)
        platform = pay.get_wallet(None)
        commission = (payment.amount * Decimal("0.10")).quantize(Decimal("0.01"))
        self.assertEqual(vendor_wallet.balance, payment.amount - commission)
        self.assertEqual(platform.balance, commission)

    def test_deposit_then_balance(self):
        booking = new_booking(payment_mode="deposit", deposit_percent=Decimal("30"))
        p1 = start(booking, "deposit")
        self.assertEqual(p1.amount, booking.deposit_amount)
        gateway_settles(p1)
        pay.verify_payment(p1)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.DEPOSIT_PAID)
        p2 = start(booking, "full")
        self.assertEqual(p2.amount, booking.balance_due)
        gateway_settles(p2)
        pay.verify_payment(p2)
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)

    def test_cancellation_refund_reverses_ledger(self):
        booking, payment = self.paid_booking(cancellation_policy="flexible")
        _, refunds = bs.cancel_booking(booking, booking.customer, "plans changed")
        self.assertEqual(len(refunds), 1)
        refund = refunds[0]
        self.assertEqual(refund.status, Refund.Status.PENDING)
        admin = make_user(role="super_admin")
        pay.process_refund(refund, admin)
        refund.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.SUCCEEDED)
        self.assertEqual(booking.amount_refunded, payment.amount)
        self.assertEqual(pay.get_wallet(booking.vendor).balance, 0)
        self.assertEqual(pay.get_wallet(None).balance, 0)

    def test_offline_payment_debits_commission(self):
        booking = new_booking(allow_pay_later=True, pay_later=True)
        owner = booking.vendor.owner
        with self.assertRaises(pay.PaymentError):
            pay.record_offline_payment(new_booking(), Decimal("1000"), "cash", owner)
        pay.record_offline_payment(booking, booking.total, "cash", owner)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        commission = (booking.total * Decimal("0.10")).quantize(Decimal("0.01"))
        self.assertEqual(pay.get_wallet(booking.vendor).balance, -commission)

    def test_payout_reserves_and_debits(self):
        booking, _ = self.paid_booking()
        vendor = booking.vendor
        available = pay.available_balance(vendor)
        payout = pay.request_payout(vendor, Decimal("50000"), vendor.owner)
        self.assertEqual(pay.available_balance(vendor), available - Decimal("50000"))
        with self.assertRaises(pay.PaymentError):
            pay.request_payout(vendor, available, vendor.owner)
        admin = make_user(role="super_admin")
        pay.review_payout(payout, admin, True)
        pay.mark_payout_paid(payout, admin, "MOMO-123")
        payout.refresh_from_db()
        self.assertEqual(payout.status, Payout.Status.PAID)
        self.assertEqual(pay.get_wallet(vendor).balance, available - Decimal("50000"))

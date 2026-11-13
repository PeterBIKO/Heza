"""Money movement. Every balance change is a LedgerEntry written under a row lock on the wallet."""
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.bookings.models import Booking
from apps.bookings.pricing import money
from apps.bookings.services import (
    BookingError,
    confirm_booking,
    lock_inventory,
    log_event,
    refresh_payment_status,
    still_available,
)
from apps.core.audit import audit
from apps.core.models import PlatformSettings

from .models import LedgerEntry, Payment, Payout, Refund, Wallet, WebhookEvent
from .providers import InvalidSignature, ProviderError, get_provider

log = logging.getLogger(__name__)
ZERO = Decimal("0")


class PaymentError(Exception):
    pass


# --- Wallets & ledger --------------------------------------------------------

def get_wallet(vendor=None, currency="RWF"):
    wallet, _created = Wallet.objects.get_or_create(vendor=vendor, currency=currency)
    return wallet


def post_entry(wallet, amount, entry_type, description, **refs):
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount == 0:
        return None
    locked = Wallet.objects.select_for_update().get(pk=wallet.pk)
    locked.balance += amount
    locked.save(update_fields=["balance", "updated_at"])
    return LedgerEntry.objects.create(wallet=locked, entry_type=entry_type, amount=amount, balance_after=locked.balance,
                                      description=description[:255], **refs)


def split_commission(amount, rate):
    commission = money(amount * rate / Decimal("100"))
    return amount - commission, commission


def reserved_for_payouts(vendor):
    return Payout.objects.filter(vendor=vendor, status__in=[Payout.Status.REQUESTED, Payout.Status.APPROVED]).aggregate(
        s=Sum("amount"))["s"] or ZERO


def available_balance(vendor):
    return get_wallet(vendor).balance - reserved_for_payouts(vendor)


# --- Checkout ----------------------------------------------------------------

def payment_options(booking):
    """What the guest may pay now: the deposit/minimum, and the full balance."""
    options = []
    if not booking.can_pay:
        return options
    minimum = booking.minimum_payment
    balance = booking.balance_due
    if booking.amount_paid == 0 and minimum < balance:
        options.append({"key": "deposit", "label": _("Pay deposit (%(p)s%%)") % {"p": f"{booking.deposit_percent.normalize():f}"}, "amount": minimum})
    options.append({"key": "full", "label": _("Pay full balance") if booking.amount_paid else _("Pay in full"), "amount": balance})
    return options


def start_payment(booking, *, option, provider_code, customer, base_url):
    provider = get_provider(provider_code)
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        choices = {o["key"]: o for o in payment_options(booking)}
        if option not in choices:
            raise PaymentError(_("This booking cannot be paid right now."))
        amount = choices[option]["amount"]
        if booking.amount_paid > 0:
            purpose = Payment.Purpose.BALANCE
        else:
            purpose = Payment.Purpose.DEPOSIT if option == "deposit" else Payment.Purpose.FULL
        payment = Payment.objects.create(booking=booking, provider=provider.code, purpose=purpose, amount=amount, currency=booking.currency)
    redirect_url = base_url.rstrip("/") + reverse("payments:return", args=[payment.reference])
    try:
        init = provider.initiate(payment, customer=customer, redirect_url=redirect_url, base_url=base_url)
    except ProviderError as exc:
        payment.status = Payment.Status.FAILED
        payment.failure_reason = str(exc)[:255]
        payment.save(update_fields=["status", "failure_reason", "updated_at"])
        raise PaymentError(_("The payment provider is unavailable: %(e)s") % {"e": exc}) from exc
    payment.checkout_url = init.checkout_url
    payment.provider_transaction_id = init.provider_reference
    payment.status = Payment.Status.PENDING
    payment.save(update_fields=["checkout_url", "provider_transaction_id", "status", "updated_at"])
    log_event(booking, _("Payment %(ref)s of %(amt)s %(cur)s started via %(p)s") % {
        "ref": payment.reference, "amt": amount, "cur": booking.currency, "p": provider.code}, customer)
    return payment


def verify_payment(payment, provider_transaction_id=""):
    """Server-side status check (used by the return URL and by reconciliation)."""
    if payment.is_final or payment.provider == "offline":
        return payment
    provider = get_provider(payment.provider)
    try:
        result = provider.verify(payment, provider_transaction_id or payment.provider_transaction_id)
    except ProviderError as exc:
        log.warning("verify failed for %s: %s", payment.reference, exc)
        return payment
    return apply_verification(payment, result)


def apply_verification(payment, result):
    notify_event = None
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == Payment.Status.SUCCESSFUL:
            return payment
        if result.tx_ref and result.tx_ref != payment.reference:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = "reference mismatch"
            payment.save()
            audit("payment.reference_mismatch", target=payment, received=result.tx_ref)
            return payment
        if result.status == "pending":
            payment.status = Payment.Status.PENDING
            payment.save(update_fields=["status", "updated_at"])
            return payment
        if result.status != "successful":
            payment.status = Payment.Status.FAILED
            payment.failure_reason = (result.failure_reason or "declined")[:255]
            payment.raw_response = result.raw
            payment.save()
            log_event(payment.booking, _("Payment %(ref)s failed: %(r)s") % {"ref": payment.reference, "r": payment.failure_reason})
            notify_event = "payment_failed"
        elif result.currency != payment.currency or result.amount < payment.amount:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = f"amount mismatch: got {result.amount} {result.currency}, expected {payment.amount} {payment.currency}"
            payment.raw_response = result.raw
            payment.save()
            audit("payment.amount_mismatch", target=payment, description=payment.failure_reason)
            log_event(payment.booking, _("Payment %(ref)s rejected: amount mismatch") % {"ref": payment.reference})
            notify_event = "payment_failed"
        else:
            payment.status = Payment.Status.SUCCESSFUL
            payment.verified_at = timezone.now()
            payment.provider_transaction_id = result.provider_transaction_id or payment.provider_transaction_id
            payment.payment_method = result.method[:40]
            payment.raw_response = result.raw
            payment.save()
            _credit_booking(payment)
            notify_event = "payment_received"
    if notify_event:
        from apps.notifications.services import notify_booking

        notify_booking(notify_event, payment.booking, payment=payment)
    return payment


def _credit_booking(payment):
    booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
    booking.amount_paid += payment.amount
    vendor_net, commission = split_commission(payment.amount, booking.commission_rate)
    desc = f"{booking.reference} · {payment.reference}"
    post_entry(get_wallet(booking.vendor, payment.currency), vendor_net, LedgerEntry.EntryType.BOOKING_INCOME, desc, booking=booking, payment=payment)
    post_entry(get_wallet(None, payment.currency), commission, LedgerEntry.EntryType.COMMISSION, desc, booking=booking, payment=payment)
    refresh_payment_status(booking)
    log_event(booking, _("Payment %(ref)s verified: %(amt)s %(cur)s") % {"ref": payment.reference, "amt": payment.amount, "cur": payment.currency})

    if booking.status in (Booking.Status.PENDING, Booking.Status.EXPIRED):
        lock_inventory(booking)
        if still_available(booking):
            if booking.status == Booking.Status.EXPIRED:
                booking.status = Booking.Status.PENDING
                log_event(booking, _("Late payment received; dates still free, booking revived"))
            booking.save()
            if booking.amount_paid >= booking.deposit_amount:
                confirm_booking(booking, message=_("Confirmed after verified payment %(ref)s") % {"ref": payment.reference})
        else:
            booking.status = Booking.Status.CANCELLED
            booking.cancelled_at = timezone.now()
            booking.cancel_reason = "Inventory no longer available when payment arrived"
            booking.save()
            log_event(booking, _("Paid after hold expired and dates were taken; full refund queued"), None, Booking.Status.EXPIRED, booking.status)
            create_refunds_for_amount(booking, payment.amount, _("Dates unavailable at payment time"), None, payment=payment)
            return
    elif booking.status == Booking.Status.CANCELLED:
        booking.save()
        create_refunds_for_amount(booking, payment.amount, _("Payment received for a cancelled booking"), None, payment=payment)
        return
    booking.save()
    overpaid = booking.amount_paid - booking.amount_refunded - booking.total
    if overpaid > 0:
        create_refunds_for_amount(booking, overpaid, _("Overpayment"), None, payment=payment)


def handle_webhook(provider_code, body, headers):
    """Returns (http_status, message). Only authenticated webhooks trigger a verify call."""
    try:
        provider = get_provider(provider_code)
    except ProviderError:
        return 404, "unknown provider"
    try:
        hook = provider.parse_webhook(body, headers)
    except InvalidSignature as exc:
        WebhookEvent.objects.create(provider=provider_code, signature_valid=False, payload={"error": str(exc)}, result="rejected: invalid signature")
        audit("payment.webhook_rejected", description=str(exc), provider=provider_code)
        return 401, "invalid signature"
    if WebhookEvent.objects.filter(provider=provider_code, event_id=hook.event_id, processed=True).exists():
        return 200, "duplicate"
    event = WebhookEvent.objects.create(provider=provider_code, event_id=hook.event_id, signature_valid=True, payload=hook.raw)
    payment = Payment.objects.filter(reference=hook.tx_ref, provider=provider_code).first()
    if payment is None:
        event.result = "unknown payment reference"
        event.save(update_fields=["result"])
        return 200, "ignored"
    try:
        result = provider.verify(payment, hook.provider_transaction_id)
    except ProviderError as exc:
        event.result = f"verify failed: {exc}"[:255]
        event.payment = payment
        event.save(update_fields=["result", "payment"])
        return 502, "verify failed"
    payment = apply_verification(payment, result)
    event.processed = True
    event.payment = payment
    event.result = payment.status
    event.save(update_fields=["processed", "payment", "result"])
    return 200, payment.status


def record_offline_payment(booking, amount, method, actor, note=""):
    """Cash/POS/MoMo collected at the property. The vendor holds the money, so Heza's commission is
    debited from the vendor wallet."""
    amount = money(amount)
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            raise PaymentError(_("Payments can only be recorded on pending or confirmed bookings."))
        if booking.status == Booking.Status.PENDING and not booking.pay_later_requested:
            raise PaymentError(_("Approve the pay-at-property request first, or ask the guest to pay online."))
        if amount <= 0 or amount > booking.balance_due:
            raise PaymentError(_("Amount must be between 1 and the balance due (%(b)s).") % {"b": booking.balance_due})
        payment = Payment.objects.create(
            booking=booking, provider="offline", purpose=Payment.Purpose.BALANCE if booking.amount_paid else Payment.Purpose.FULL,
            amount=amount, currency=booking.currency, status=Payment.Status.SUCCESSFUL, payment_method=method[:40],
            verified_at=timezone.now(), recorded_by=actor, raw_response={"note": note[:200]},
        )
        booking.amount_paid += amount
        _net, commission = split_commission(amount, booking.commission_rate)
        desc = f"{booking.reference} · collected at property ({method})"
        post_entry(get_wallet(booking.vendor), -commission, LedgerEntry.EntryType.OFFLINE_COLLECTION, desc, booking=booking, payment=payment, created_by=actor)
        post_entry(get_wallet(None), commission, LedgerEntry.EntryType.COMMISSION, desc, booking=booking, payment=payment, created_by=actor)
        refresh_payment_status(booking)
        booking.save()
        log_event(booking, _("%(amt)s %(cur)s collected at property via %(m)s") % {"amt": amount, "cur": booking.currency, "m": method}, actor)
        if booking.status == Booking.Status.PENDING:
            lock_inventory(booking)
            if not still_available(booking):
                raise PaymentError(_("The dates are no longer available."))
            booking.pay_later_approved = True
            confirm_booking(booking, actor, _("Confirmed after payment collected at property"))
    audit("payment.offline_recorded", actor=actor, target=booking, amount=str(amount), method=method)
    return payment


# --- Refunds -----------------------------------------------------------------

def refundable_on(payment):
    taken = payment.refunds.exclude(status__in=[Refund.Status.FAILED, Refund.Status.REJECTED]).aggregate(s=Sum("amount"))["s"] or ZERO
    return payment.amount - taken


def create_refunds_for_amount(booking, amount, reason, actor, payment=None):
    """Queue refunds (admin approval) spread over the booking's online payments, newest first."""
    remaining = money(amount)
    payments = [payment] if payment else list(booking.payments.filter(status=Payment.Status.SUCCESSFUL).exclude(provider="offline").order_by("-created_at"))
    refunds = []
    for p in payments:
        if remaining <= 0:
            break
        part = min(refundable_on(p), remaining)
        if part <= 0:
            continue
        refunds.append(Refund.objects.create(
            booking=booking, payment=p, amount=part, currency=p.currency, reason=str(reason)[:255],
            requested_by=actor if getattr(actor, "is_authenticated", False) else None,
        ))
        remaining -= part
    if refunds:
        log_event(booking, _("Refund of %(amt)s %(cur)s queued for approval") % {"amt": sum(r.amount for r in refunds), "cur": booking.currency})
    return refunds


def process_refund(refund, actor):
    with transaction.atomic():
        refund = Refund.objects.select_for_update().select_related("payment", "booking").get(pk=refund.pk)
        if refund.status not in (Refund.Status.PENDING, Refund.Status.FAILED):
            raise PaymentError(_("This refund has already been processed."))
        if refund.amount > refund.payment.amount:
            raise PaymentError(_("Refund exceeds the original payment."))
        try:
            result = get_provider(refund.payment.provider).refund(refund.payment, refund.amount)
        except ProviderError as exc:
            refund.status = Refund.Status.FAILED
            refund.failure_reason = str(exc)[:255]
            refund.save()
            return refund
        refund.provider_refund_id = result.provider_refund_id
        refund.processed_by = actor
        refund.processed_at = timezone.now()
        if result.status == "failed":
            refund.status = Refund.Status.FAILED
            refund.failure_reason = result.failure_reason[:255]
            refund.save()
            audit("refund.failed", actor=actor, target=refund, description=refund.failure_reason)
            return refund
        if result.status == "processing":
            refund.status = Refund.Status.PROCESSING
            refund.save()
            return refund
        _settle_refund(refund, actor)
    audit("refund.succeeded", actor=actor, target=refund, amount=str(refund.amount))
    from apps.notifications.services import notify_booking

    notify_booking("refund_processed", refund.booking, refund=refund)
    return refund


def mark_refund_settled(refund, actor):
    """For refunds the provider reported as processing and later confirmed in its dashboard."""
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        if refund.status != Refund.Status.PROCESSING:
            raise PaymentError(_("Only processing refunds can be marked as settled."))
        refund.processed_by = actor
        refund.processed_at = timezone.now()
        _settle_refund(refund, actor)
    audit("refund.settled_manually", actor=actor, target=refund)
    return refund


def _settle_refund(refund, actor):
    refund.status = Refund.Status.SUCCEEDED
    refund.save()
    booking = Booking.objects.select_for_update().get(pk=refund.booking_id)
    booking.amount_refunded += refund.amount
    vendor_part, commission_part = split_commission(refund.amount, booking.commission_rate)
    desc = f"Refund {booking.reference} · {refund.reason}"
    post_entry(get_wallet(booking.vendor, refund.currency), -vendor_part, LedgerEntry.EntryType.REFUND, desc, booking=booking, refund=refund, created_by=actor)
    post_entry(get_wallet(None, refund.currency), -commission_part, LedgerEntry.EntryType.COMMISSION_REVERSAL, desc, booking=booking, refund=refund, created_by=actor)
    refresh_payment_status(booking)
    if booking.status == Booking.Status.CANCELLED and not booking.refunds.filter(status__in=[Refund.Status.PENDING, Refund.Status.PROCESSING]).exists():
        old = booking.status
        booking.status = Booking.Status.REFUNDED
        log_event(booking, _("Refund of %(amt)s %(cur)s completed") % {"amt": refund.amount, "cur": refund.currency}, actor, old, booking.status)
    else:
        log_event(booking, _("Refund of %(amt)s %(cur)s completed") % {"amt": refund.amount, "cur": refund.currency}, actor)
    booking.save()


def reject_refund(refund, actor, note):
    if refund.status != Refund.Status.PENDING:
        raise PaymentError(_("Only pending refunds can be rejected."))
    refund.status = Refund.Status.REJECTED
    refund.failure_reason = note[:255]
    refund.processed_by = actor
    refund.processed_at = timezone.now()
    refund.save()
    log_event(refund.booking, _("Refund rejected by Heza: %(n)s") % {"n": note}, actor)
    audit("refund.rejected", actor=actor, target=refund, description=note)
    return refund


# --- Payouts -----------------------------------------------------------------

def request_payout(vendor, amount, actor):
    amount = money(amount)
    minimum = PlatformSettings.load().min_payout_amount
    with transaction.atomic():
        Wallet.objects.select_for_update().filter(pk=get_wallet(vendor).pk).first()
        avail = available_balance(vendor)
        if amount < minimum:
            raise PaymentError(_("Minimum payout is %(m)s RWF.") % {"m": minimum})
        if amount > avail:
            raise PaymentError(_("You can request up to %(a)s RWF.") % {"a": avail})
        if vendor.payout_method == "momo" and not vendor.payout_momo_number or vendor.payout_method == "bank" and not vendor.payout_account_number:
            raise PaymentError(_("Add your payout details in business settings first."))
        payout = Payout.objects.create(vendor=vendor, amount=amount, destination=vendor.payout_destination, requested_by=actor)
    audit("payout.requested", actor=actor, target=payout, amount=str(amount))
    from apps.notifications.services import notify_admins

    notify_admins("payout_requested", _("Payout request: %(v)s · %(a)s RWF") % {"v": vendor, "a": amount}, reverse("adminpanel:payouts"))
    return payout


def review_payout(payout, actor, approve, note=""):
    if payout.status != Payout.Status.REQUESTED:
        raise PaymentError(_("This payout has already been reviewed."))
    payout.status = Payout.Status.APPROVED if approve else Payout.Status.REJECTED
    payout.reviewed_by = actor
    payout.reviewed_at = timezone.now()
    payout.note = note[:255]
    payout.save()
    audit("payout.approved" if approve else "payout.rejected", actor=actor, target=payout, description=note)
    from apps.notifications.services import notify_vendor

    notify_vendor(payout.vendor, "payout_update", _("Payout %(s)s: %(a)s RWF") % {"s": payout.get_status_display().lower(), "a": payout.amount}, note)
    return payout


def mark_payout_paid(payout, actor, transfer_reference):
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(pk=payout.pk)
        if payout.status != Payout.Status.APPROVED:
            raise PaymentError(_("Approve the payout before marking it paid."))
        wallet = get_wallet(payout.vendor, payout.currency)
        if wallet.balance < payout.amount:
            raise PaymentError(_("Vendor wallet balance is below the payout amount."))
        payout.status = Payout.Status.PAID
        payout.paid_at = timezone.now()
        payout.transfer_reference = transfer_reference[:80]
        payout.save()
        post_entry(wallet, -payout.amount, LedgerEntry.EntryType.PAYOUT, f"Payout to {payout.destination} · {transfer_reference}", payout=payout, created_by=actor)
    audit("payout.paid", actor=actor, target=payout, reference=transfer_reference)
    from apps.notifications.services import notify_vendor

    notify_vendor(payout.vendor, "payout_update", _("Payout sent: %(a)s RWF") % {"a": payout.amount}, _("Transfer reference %(r)s") % {"r": transfer_reference})
    return payout


__all__ = [
    "BookingError", "PaymentError", "get_wallet", "start_payment", "verify_payment", "apply_verification", "handle_webhook",
    "record_offline_payment", "create_refunds_for_amount", "process_refund", "reject_refund", "request_payout", "review_payout",
    "mark_payout_paid", "payment_options", "available_balance",
]

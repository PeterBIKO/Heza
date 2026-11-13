import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.properties.models import MONEY


def payment_reference():
    return "HZP-" + uuid.uuid4().hex[:16].upper()


class Payment(TimeStampedModel):
    class Status(models.TextChoices):
        INITIATED = "initiated", _("Initiated")
        PENDING = "pending", _("Pending")
        SUCCESSFUL = "successful", _("Successful")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    class Purpose(models.TextChoices):
        FULL = "full", _("Full payment")
        DEPOSIT = "deposit", _("Deposit")
        BALANCE = "balance", _("Balance")

    booking = models.ForeignKey("bookings.Booking", on_delete=models.PROTECT, related_name="payments")
    reference = models.CharField(max_length=40, unique=True, default=payment_reference, editable=False)
    provider = models.CharField(max_length=20, db_index=True)
    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="RWF")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INITIATED, db_index=True)
    provider_transaction_id = models.CharField(max_length=80, blank=True, db_index=True)
    checkout_url = models.URLField(max_length=500, blank=True)
    payment_method = models.CharField(max_length=40, blank=True, help_text=_("card / mobilemoneyrw / cash …"))
    failure_reason = models.CharField(max_length=255, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text=_("Staff member who recorded an offline (cash/POS) payment"),
    )
    # Only sanitised gateway responses are kept: no PAN, CVV or tokens are ever sent to or stored by Heza.
    raw_response = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency} ({self.status})"

    @property
    def is_final(self):
        return self.status in (self.Status.SUCCESSFUL, self.Status.FAILED, self.Status.CANCELLED)


class WebhookEvent(models.Model):
    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=120, blank=True, db_index=True)
    signature_valid = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    result = models.CharField(max_length=255, blank=True)
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="webhooks")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]


class Wallet(models.Model):
    """One wallet per vendor plus one platform wallet (vendor=NULL). Balances move only via LedgerEntry."""

    vendor = models.OneToOneField("vendors.Vendor", null=True, blank=True, on_delete=models.PROTECT, related_name="wallet")
    currency = models.CharField(max_length=3, default="RWF")
    balance = models.DecimalField(**MONEY, default=Decimal("0"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["currency"], condition=models.Q(vendor__isnull=True), name="one_platform_wallet_per_currency")
        ]

    def __str__(self):
        return f"Wallet {self.vendor or 'Heza platform'} {self.balance} {self.currency}"

    @property
    def is_platform(self):
        return self.vendor_id is None


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        BOOKING_INCOME = "booking_income", _("Booking income (net of commission)")
        COMMISSION = "commission", _("Platform commission")
        REFUND = "refund", _("Refund")
        COMMISSION_REVERSAL = "commission_reversal", _("Commission reversal")
        PAYOUT = "payout", _("Payout")
        PAYOUT_REVERSAL = "payout_reversal", _("Payout reversal")
        OFFLINE_COLLECTION = "offline_collection", _("Collected at property (commission owed)")
        ADJUSTMENT = "adjustment", _("Manual adjustment")

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="entries")
    entry_type = models.CharField(max_length=24, choices=EntryType.choices)
    amount = models.DecimalField(**MONEY, help_text=_("Positive = credit, negative = debit"))
    balance_after = models.DecimalField(**MONEY)
    booking = models.ForeignKey("bookings.Booking", null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    payout = models.ForeignKey("payments.Payout", null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    refund = models.ForeignKey("payments.Refund", null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    description = models.CharField(max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "ledger entries"


class Refund(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Awaiting approval")
        PROCESSING = "processing", _("Processing")
        SUCCEEDED = "succeeded", _("Refunded")
        FAILED = "failed", _("Failed")
        REJECTED = "rejected", _("Rejected")

    booking = models.ForeignKey("bookings.Booking", on_delete=models.PROTECT, related_name="refunds")
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="RWF")
    reason = models.CharField(max_length=255)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    provider_refund_id = models.CharField(max_length=80, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund {self.amount} for {self.booking}"


class Payout(TimeStampedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        APPROVED = "approved", _("Approved")
        PAID = "paid", _("Paid")
        REJECTED = "rejected", _("Rejected")

    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.PROTECT, related_name="payouts")
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="RWF")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    destination = models.CharField(max_length=255)
    transfer_reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=255, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payout {self.amount} to {self.vendor}"


def sandbox_txn_id():
    return "SBX-" + secrets.token_hex(8).upper()


class SandboxTransaction(models.Model):
    """State owned by the simulated external gateway. The app only learns about it through
    signed webhooks and server-side verify calls, exactly like a real provider."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCESSFUL = "successful", _("Successful")
        FAILED = "failed", _("Failed")

    txn_id = models.CharField(max_length=40, unique=True, default=sandbox_txn_id)
    tx_ref = models.CharField(max_length=40, unique=True)
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3)
    customer_email = models.EmailField()
    redirect_url = models.URLField(max_length=500)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    method = models.CharField(max_length=20, blank=True)
    refunded_amount = models.DecimalField(**MONEY, default=Decimal("0"))
    created_at = models.DateTimeField(auto_now_add=True)

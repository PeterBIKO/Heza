import builtins
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import PERCENT_VALIDATORS, TimeStampedModel
from apps.properties.models import MONEY, CancellationPolicy

REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_reference():
    return "HZ-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(8))


class BookingQuerySet(models.QuerySet):
    def holding_inventory(self, now=None):
        """Bookings that occupy inventory: confirmed/completed, or pending with a live hold."""
        now = now or timezone.now()
        return self.filter(
            models.Q(status__in=[Booking.Status.CONFIRMED, Booking.Status.COMPLETED])
            | models.Q(status=Booking.Status.PENDING, hold_expires_at__gt=now)
            | models.Q(status=Booking.Status.PENDING, pay_later_requested=True)
        )


class Booking(TimeStampedModel):
    class Kind(models.TextChoices):
        ROOM = "room", _("Room stay")
        VENUE = "venue", _("Venue / event")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        CANCELLED = "cancelled", _("Cancelled")
        COMPLETED = "completed", _("Completed")
        REFUNDED = "refunded", _("Refunded")
        EXPIRED = "expired", _("Expired")

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", _("Unpaid")
        DEPOSIT_PAID = "deposit_paid", _("Deposit paid")
        PAID = "paid", _("Paid in full")
        PARTIALLY_REFUNDED = "partially_refunded", _("Partially refunded")
        REFUNDED = "refunded", _("Refunded")

    class VenueMode(models.TextChoices):
        HOURLY = "hourly", _("Hourly")
        HALF_DAY_AM = "half_day_am", _("Half day — morning")
        HALF_DAY_PM = "half_day_pm", _("Half day — afternoon")
        FULL_DAY = "full_day", _("Full day")
        EVENT = "event", _("Whole event (day + evening)")

    reference = models.CharField(max_length=16, unique=True, default=generate_reference, editable=False)
    kind = models.CharField(max_length=6, choices=Kind.choices)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="bookings")
    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.PROTECT, related_name="bookings")

    room_type = models.ForeignKey("properties.RoomType", null=True, blank=True, on_delete=models.PROTECT, related_name="bookings")
    rooms = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    check_in = models.DateField(null=True, blank=True, db_index=True)
    check_out = models.DateField(null=True, blank=True, db_index=True)
    adults = models.PositiveSmallIntegerField(default=1)
    children = models.PositiveSmallIntegerField(default=0)

    venue = models.ForeignKey("properties.Venue", null=True, blank=True, on_delete=models.PROTECT, related_name="bookings")
    venue_mode = models.CharField(max_length=12, choices=VenueMode.choices, blank=True)
    start_at = models.DateTimeField(null=True, blank=True, db_index=True)
    end_at = models.DateTimeField(null=True, blank=True)
    guests = models.PositiveIntegerField(default=1)
    package = models.ForeignKey("properties.VenuePackage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    event_type = models.CharField(max_length=80, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True)
    currency = models.CharField(max_length=3, default="RWF")
    subtotal = models.DecimalField(**MONEY, default=Decimal("0"))
    discount_amount = models.DecimalField(**MONEY, default=Decimal("0"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    tax_amount = models.DecimalField(**MONEY, default=Decimal("0"))
    total = models.DecimalField(**MONEY, default=Decimal("0"))
    deposit_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("100"), validators=PERCENT_VALIDATORS)
    deposit_amount = models.DecimalField(**MONEY, default=Decimal("0"))
    amount_paid = models.DecimalField(**MONEY, default=Decimal("0"))
    amount_refunded = models.DecimalField(**MONEY, default=Decimal("0"))
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10"))
    coupon = models.ForeignKey("bookings.Coupon", null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings")
    price_breakdown = models.JSONField(default=list, blank=True)

    cancellation_policy = models.CharField(max_length=20, choices=CancellationPolicy.choices, default=CancellationPolicy.MODERATE)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    pay_later_requested = models.BooleanField(default=False)
    pay_later_approved = models.BooleanField(default=False)

    guest_name = models.CharField(max_length=120)
    guest_email = models.EmailField()
    guest_phone = models.CharField(max_length=20)
    special_requests = models.TextField(blank=True, max_length=2000)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cancel_reason = models.CharField(max_length=255, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["room_type", "check_in", "check_out"]),
            models.Index(fields=["venue", "start_at", "end_at"]),
            models.Index(fields=["vendor", "status"]),
        ]

    def __str__(self):
        return self.reference

    def get_absolute_url(self):
        return reverse("bookings:detail", args=[self.reference])

    @builtins.property
    def nights(self):
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return 0

    @builtins.property
    def hours(self):
        if self.start_at and self.end_at:
            return round((self.end_at - self.start_at).total_seconds() / 3600, 1)
        return 0

    @builtins.property
    def balance_due(self):
        return max(self.total - self.amount_paid, Decimal("0"))

    @builtins.property
    def listing_name(self):
        if self.kind == self.Kind.ROOM and self.room_type_id:
            return self.room_type.name
        if self.venue_id:
            return self.venue.name
        return self.property.name

    @builtins.property
    def starts_on(self):
        if self.kind == self.Kind.ROOM:
            return self.check_in
        return timezone.localtime(self.start_at).date() if self.start_at else None

    @builtins.property
    def is_active_hold(self):
        return self.status == self.Status.PENDING and (
            self.pay_later_requested or (self.hold_expires_at and self.hold_expires_at > timezone.now())
        )

    @builtins.property
    def can_pay(self):
        return self.status in (self.Status.PENDING, self.Status.CONFIRMED) and self.balance_due > 0 and (
            self.status == self.Status.CONFIRMED or self.is_active_hold
        )

    @builtins.property
    def minimum_payment(self):
        """Amount the next payment must at least cover: the deposit first, then the balance."""
        if self.amount_paid < self.deposit_amount:
            return self.deposit_amount - self.amount_paid
        return self.balance_due

    @builtins.property
    def commission_amount(self):
        net_paid = self.amount_paid - self.amount_refunded
        return (net_paid * self.commission_rate / Decimal("100")).quantize(Decimal("0.01"))


class BookingExtra(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="extras")
    extra = models.ForeignKey("properties.VenueExtra", null=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(**MONEY)
    quantity = models.PositiveIntegerField(default=1)
    total = models.DecimalField(**MONEY)


class BookingEvent(models.Model):
    """Status history and audit trail of a booking."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    from_status = models.CharField(max_length=10, blank=True)
    to_status = models.CharField(max_length=10, blank=True)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class Coupon(TimeStampedModel):
    code = models.CharField(max_length=30, unique=True)
    vendor = models.ForeignKey(
        "vendors.Vendor", null=True, blank=True, on_delete=models.CASCADE, related_name="coupons",
        help_text=_("Empty = platform-wide coupon funded by Heza"),
    )
    description = models.CharField(max_length=140, blank=True)
    percent_off = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=PERCENT_VALIDATORS)
    amount_off = models.DecimalField(**MONEY, null=True, blank=True)
    min_subtotal = models.DecimalField(**MONEY, default=Decimal("0"))
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    times_used = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def is_valid_for(self, property_obj, subtotal, on_date=None):
        today = on_date or timezone.localdate()
        if not self.is_active:
            return False, _("This code is no longer active.")
        if self.vendor_id and self.vendor_id != property_obj.vendor_id:
            return False, _("This code is not valid for this property.")
        if self.valid_from and today < self.valid_from:
            return False, _("This code is not active yet.")
        if self.valid_until and today > self.valid_until:
            return False, _("This code has expired.")
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False, _("This code has been fully redeemed.")
        if subtotal < self.min_subtotal:
            return False, _("Your booking is below the minimum for this code.")
        return True, ""

    def discount_for(self, subtotal):
        amount = Decimal("0")
        if self.percent_off:
            amount = subtotal * self.percent_off / Decimal("100")
        elif self.amount_off:
            amount = self.amount_off
        return min(amount, subtotal).quantize(Decimal("1"))

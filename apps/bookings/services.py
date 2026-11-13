"""Booking engine. All state transitions go through this module.

Concurrency: every create/modify locks the inventory row (RoomType or Venue) with SELECT ... FOR UPDATE
inside a transaction, re-counts overlapping bookings, then writes. Two guests racing for the last room
are serialised by PostgreSQL, so the second sees zero availability.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.audit import audit
from apps.properties.models import (
    CancellationPolicy,
    RoomType,
    Venue,
    VenueExtra,
    VenuePackage,
)

from . import availability
from .models import Booking, BookingEvent, BookingExtra, Coupon
from .pricing import money, quote_room, quote_venue, venue_window

MAX_NIGHTS = 60
MAX_ADVANCE_DAYS = 540


class BookingError(Exception):
    pass


@dataclass
class GuestDetails:
    name: str
    email: str
    phone: str
    special_requests: str = ""


def log_event(booking, message, actor=None, from_status="", to_status=""):
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    BookingEvent.objects.create(
        booking=booking, actor=actor, message=message[:255], from_status=from_status, to_status=to_status
    )


def _hold_deadline():
    return timezone.now() + timedelta(minutes=settings.BOOKING_HOLD_MINUTES)


def _apply_quote(booking, quote):
    booking.subtotal = quote.subtotal
    booking.discount_amount = quote.discount
    booking.tax_rate = quote.tax_rate
    booking.tax_amount = quote.tax
    booking.total = quote.total
    booking.deposit_percent = quote.deposit_percent
    booking.deposit_amount = quote.deposit
    booking.commission_rate = quote.commission_rate
    booking.coupon = quote.coupon
    booking.price_breakdown = quote.lines


def validate_stay(room_type, check_in, check_out, rooms, adults, children):
    today = timezone.localdate()
    if check_in is None or check_out is None:
        raise BookingError(_("Choose your check-in and check-out dates."))
    if check_in < today:
        raise BookingError(_("Check-in cannot be in the past."))
    if check_out <= check_in:
        raise BookingError(_("Check-out must be after check-in."))
    if (check_out - check_in).days > MAX_NIGHTS:
        raise BookingError(_("Stays are limited to %(n)s nights per booking.") % {"n": MAX_NIGHTS})
    if (check_in - today).days > MAX_ADVANCE_DAYS:
        raise BookingError(_("That date is too far ahead to book."))
    if rooms < 1:
        raise BookingError(_("Book at least one room."))
    if adults < 1:
        raise BookingError(_("At least one adult is required."))
    if adults > room_type.max_adults * rooms or children > room_type.max_children * rooms:
        raise BookingError(
            _("%(room)s sleeps %(a)s adults and %(c)s children per unit. Add rooms or choose a larger room.")
            % {"room": room_type.name, "a": room_type.max_adults, "c": room_type.max_children}
        )
    min_nights = max([r.min_nights for r in room_type.seasonal_rates.filter(start_date__lte=check_in, end_date__gte=check_in)] or [1])
    if (check_out - check_in).days < min_nights:
        raise BookingError(_("Minimum stay for these dates is %(n)s nights.") % {"n": min_nights})


def _ensure_bookable(prop):
    if not prop.is_public:
        raise BookingError(_("This property is not accepting bookings right now."))


def create_room_booking(*, customer, room_type_id, check_in, check_out, rooms, adults, children, guest, coupon_code="", pay_later=False):
    with transaction.atomic():
        room_type = RoomType.objects.select_for_update().select_related("property__vendor").get(pk=room_type_id)
        prop = room_type.property
        _ensure_bookable(prop)
        validate_stay(room_type, check_in, check_out, rooms, adults, children)
        if pay_later and not prop.allow_pay_later:
            raise BookingError(_("This property requires payment online."))
        free = availability.units_available(room_type, check_in, check_out)
        if free < rooms:
            raise BookingError(
                _("Sorry, only %(n)s unit(s) of %(room)s are free for those dates.") % {"n": free, "room": room_type.name}
                if free
                else _("Sorry, %(room)s is fully booked for those dates.") % {"room": room_type.name}
            )
        quote = quote_room(room_type, check_in, check_out, rooms, coupon_code)
        if coupon_code and quote.coupon_error:
            raise BookingError(quote.coupon_error)
        booking = Booking(
            kind=Booking.Kind.ROOM, customer=customer, property=prop, vendor=prop.vendor, room_type=room_type,
            rooms=rooms, check_in=check_in, check_out=check_out, adults=adults, children=children,
            guests=adults + children, cancellation_policy=prop.cancellation_policy,
            hold_expires_at=_hold_deadline(), pay_later_requested=pay_later,
            guest_name=guest.name, guest_email=guest.email, guest_phone=guest.phone, special_requests=guest.special_requests,
        )
        _apply_quote(booking, quote)
        booking.save()
        log_event(booking, _("Booking created; inventory held"), customer, "", booking.status)
    _after_create(booking)
    return booking


def create_venue_booking(*, customer, venue_id, day, mode, start_time=None, hours=None, guests, package_id=None,
                         extras=None, event_type="", guest, coupon_code="", pay_later=False):
    """extras: dict {extra_id: quantity}"""
    with transaction.atomic():
        venue = Venue.objects.select_for_update().select_related("property__vendor").get(pk=venue_id)
        prop = venue.property
        _ensure_bookable(prop)
        if pay_later and not prop.allow_pay_later:
            raise BookingError(_("This venue requires payment online."))
        if day is None or day < timezone.localdate():
            raise BookingError(_("Choose an event date from today onwards."))
        if (day - timezone.localdate()).days > MAX_ADVANCE_DAYS:
            raise BookingError(_("That date is too far ahead to book."))
        if guests < 1 or guests > venue.max_capacity:
            raise BookingError(_("%(venue)s holds up to %(n)s guests.") % {"venue": venue.name, "n": venue.max_capacity})
        if mode == "hourly":
            if not hours or int(hours) < venue.min_hours:
                raise BookingError(_("Minimum booking is %(n)s hours.") % {"n": venue.min_hours})
        try:
            start_at, end_at = venue_window(venue, mode, day, start_time, hours)
        except ValueError as exc:
            raise BookingError(str(exc)) from exc
        open_at, close_at = venue_window(venue, "event", day)
        if start_at < open_at or end_at > close_at:
            raise BookingError(
                _("%(venue)s is open %(o)s–%(c)s.") % {"venue": venue.name, "o": venue.opening_time.strftime("%H:%M"), "c": venue.closing_time.strftime("%H:%M")}
            )
        if start_at <= timezone.now():
            raise BookingError(_("That time has already passed."))
        if not availability.venue_is_free(venue, start_at, end_at):
            raise BookingError(_("%(venue)s is already booked for that time. Pick another slot.") % {"venue": venue.name})
        package = VenuePackage.objects.filter(pk=package_id, venue=venue, is_active=True).first() if package_id else None
        extra_rows = []
        for extra in VenueExtra.objects.filter(venue=venue, is_active=True, pk__in=list((extras or {}).keys())):
            qty = int((extras or {}).get(extra.pk) or (extras or {}).get(str(extra.pk)) or 0)
            if qty > 0:
                extra_rows.append((extra, min(qty, 1000)))
        try:
            quote = quote_venue(venue, mode, start_at, end_at, guests, package, extra_rows, coupon_code)
        except ValueError as exc:
            raise BookingError(str(exc)) from exc
        if coupon_code and quote.coupon_error:
            raise BookingError(quote.coupon_error)
        booking = Booking(
            kind=Booking.Kind.VENUE, customer=customer, property=prop, vendor=prop.vendor, venue=venue, venue_mode=mode,
            start_at=start_at, end_at=end_at, guests=guests, adults=guests, package=package, event_type=event_type[:80],
            cancellation_policy=prop.cancellation_policy, hold_expires_at=_hold_deadline(), pay_later_requested=pay_later,
            guest_name=guest.name, guest_email=guest.email, guest_phone=guest.phone, special_requests=guest.special_requests,
        )
        _apply_quote(booking, quote)
        booking.save()
        lines = {line["label"]: line for line in quote.lines}
        for extra, qty in extra_rows:
            match = next((v for k, v in lines.items() if k.startswith(extra.name)), None)
            BookingExtra.objects.create(
                booking=booking, extra=extra, name=extra.name, unit_price=extra.price, quantity=match["qty"] if match else qty,
                total=Decimal(match["amount"]) if match else extra.price * qty,
            )
        log_event(booking, _("Booking created; venue slot held"), customer, "", booking.status)
    _after_create(booking)
    return booking


def _after_create(booking):
    from apps.notifications.services import notify_booking

    notify_booking("booking_created", booking)
    if booking.pay_later_requested:
        notify_booking("vendor_pay_later_request", booking)


def refresh_payment_status(booking):
    if booking.amount_refunded > 0:
        booking.payment_status = (
            Booking.PaymentStatus.REFUNDED if booking.amount_refunded >= booking.amount_paid else Booking.PaymentStatus.PARTIALLY_REFUNDED
        )
    elif booking.amount_paid >= booking.total and booking.total > 0:
        booking.payment_status = Booking.PaymentStatus.PAID
    elif booking.amount_paid > 0:
        booking.payment_status = Booking.PaymentStatus.DEPOSIT_PAID
    else:
        booking.payment_status = Booking.PaymentStatus.UNPAID


def still_available(booking):
    if booking.kind == Booking.Kind.ROOM:
        return availability.units_available(booking.room_type, booking.check_in, booking.check_out, exclude=booking) >= booking.rooms
    return availability.venue_is_free(booking.venue, booking.start_at, booking.end_at, exclude=booking)


def lock_inventory(booking):
    if booking.kind == Booking.Kind.ROOM:
        RoomType.objects.select_for_update().get(pk=booking.room_type_id)
    else:
        Venue.objects.select_for_update().get(pk=booking.venue_id)


def confirm_booking(booking, actor=None, message=None):
    """Caller must hold a transaction. Confirms a pending booking (payment verified or pay-later approved)."""
    if booking.status != Booking.Status.PENDING:
        return booking
    old = booking.status
    booking.status = Booking.Status.CONFIRMED
    booking.confirmed_at = timezone.now()
    booking.hold_expires_at = None
    booking.save()
    if booking.coupon_id:
        Coupon.objects.filter(pk=booking.coupon_id).update(times_used=F("times_used") + 1)
    log_event(booking, message or _("Booking confirmed"), actor, old, booking.status)
    transaction.on_commit(lambda: _notify_confirmed(booking.pk))
    return booking


def _notify_confirmed(pk):
    from apps.notifications.services import notify_booking

    booking = Booking.objects.get(pk=pk)
    notify_booking("booking_confirmed", booking)
    notify_booking("vendor_new_booking", booking)


def approve_pay_later(booking, actor):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status != Booking.Status.PENDING or not booking.pay_later_requested:
            raise BookingError(_("This booking is not awaiting a pay-at-property approval."))
        lock_inventory(booking)
        if not still_available(booking):
            raise BookingError(_("The dates are no longer available."))
        booking.pay_later_approved = True
        confirm_booking(booking, actor, _("Pay-at-property approved by vendor"))
    audit("booking.pay_later_approved", actor=actor, target=booking)
    return booking


def decline_pay_later(booking, actor, reason=""):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status != Booking.Status.PENDING or not booking.pay_later_requested:
            raise BookingError(_("This booking is not awaiting a pay-at-property approval."))
        booking.pay_later_requested = False
        booking.hold_expires_at = _hold_deadline()
        booking.save()
        log_event(booking, _("Pay-at-property declined: %(r)s. Guest may still pay online.") % {"r": reason or "—"}, actor)
    from apps.notifications.services import notify_booking

    notify_booking("pay_later_declined", booking)
    return booking


def hours_until_start(booking, now=None):
    now = now or timezone.now()
    if booking.kind == Booking.Kind.ROOM:
        start = timezone.make_aware(
            datetime.combine(booking.check_in, booking.property.check_in_time), timezone.get_current_timezone()
        )
    else:
        start = booking.start_at
    return (start - now).total_seconds() / 3600


def refund_percent(booking, now=None):
    hours = hours_until_start(booking, now)
    policy = booking.cancellation_policy
    if hours <= 0:
        return Decimal("0")
    if policy == CancellationPolicy.FLEXIBLE:
        return Decimal("100") if hours >= 24 else Decimal("0")
    if policy == CancellationPolicy.MODERATE:
        return Decimal("100") if hours >= 24 * 5 else Decimal("50")
    if policy == CancellationPolicy.STRICT:
        return Decimal("50") if hours >= 24 * 7 else Decimal("0")
    return Decimal("0")


def cancellation_preview(booking, by_vendor=False):
    paid_online = sum((p.amount for p in booking.payments.filter(status="successful").exclude(provider="offline")), Decimal("0"))
    refundable_base = paid_online - booking.amount_refunded
    pct = Decimal("100") if by_vendor else refund_percent(booking)
    return {"percent": pct, "amount": money(max(refundable_base, Decimal("0")) * pct / Decimal("100")), "paid": booking.amount_paid}


def cancel_booking(booking, actor, reason="", by_vendor=False):
    from apps.payments.services import create_refunds_for_amount

    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            raise BookingError(_("Only pending or confirmed bookings can be cancelled."))
        if not by_vendor and booking.status == Booking.Status.CONFIRMED and hours_until_start(booking) <= 0:
            raise BookingError(_("This booking has already started. Contact the property."))
        preview = cancellation_preview(booking, by_vendor=by_vendor)
        old = booking.status
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancelled_by = actor if getattr(actor, "is_authenticated", False) else None
        booking.cancel_reason = reason[:255]
        booking.hold_expires_at = None
        booking.save()
        who = _("vendor") if by_vendor else _("guest")
        log_event(booking, _("Cancelled by %(who)s. %(r)s") % {"who": who, "r": reason}, actor, old, booking.status)
        refunds = []
        if preview["amount"] > 0:
            refunds = create_refunds_for_amount(booking, preview["amount"], _("Cancellation (%(p)s%% refund)") % {"p": preview["percent"]}, actor)
    audit("booking.cancelled", actor=actor, target=booking, description=reason, by_vendor=by_vendor, refund=str(preview["amount"]))
    from apps.notifications.services import notify_booking

    notify_booking("booking_cancelled", booking)
    notify_booking("vendor_booking_cancelled", booking)
    return booking, refunds


def modify_booking(booking, actor, *, check_in=None, check_out=None, rooms=None, adults=None, children=None,
                   day=None, mode=None, start_time=None, hours=None, guests=None):
    """Change dates/party size. Re-checks availability excluding this booking and re-prices.
    If the new total is lower than what was paid, the difference is queued as a refund."""
    from apps.payments.services import create_refunds_for_amount

    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            raise BookingError(_("This booking can no longer be changed."))
        if not booking.property.allow_modifications:
            raise BookingError(_("This property does not accept online changes. Please contact them."))
        if hours_until_start(booking) < 24:
            raise BookingError(_("Changes are allowed up to 24 hours before arrival."))
        lock_inventory(booking)
        old_summary = _summary(booking)
        coupon_code = booking.coupon.code if booking.coupon_id else ""
        if booking.kind == Booking.Kind.ROOM:
            check_in, check_out = check_in or booking.check_in, check_out or booking.check_out
            rooms = rooms or booking.rooms
            adults = adults if adults is not None else booking.adults
            children = children if children is not None else booking.children
            validate_stay(booking.room_type, check_in, check_out, rooms, adults, children)
            if availability.units_available(booking.room_type, check_in, check_out, exclude=booking) < rooms:
                raise BookingError(_("Those dates are not available for this room."))
            quote = quote_room(booking.room_type, check_in, check_out, rooms, coupon_code)
            booking.check_in, booking.check_out, booking.rooms = check_in, check_out, rooms
            booking.adults, booking.children, booking.guests = adults, children, adults + children
        else:
            venue = booking.venue
            day = day or timezone.localtime(booking.start_at).date()
            mode = mode or booking.venue_mode
            guests = guests or booking.guests
            if guests > venue.max_capacity:
                raise BookingError(_("Too many guests for this venue."))
            try:
                start_at, end_at = venue_window(venue, mode, day, start_time, hours)
            except ValueError as exc:
                raise BookingError(str(exc)) from exc
            if start_at <= timezone.now() or not availability.venue_is_free(venue, start_at, end_at, exclude=booking):
                raise BookingError(_("That time is not available."))
            extras = [(e.extra, e.quantity) for e in booking.extras.select_related("extra") if e.extra]
            quote = quote_venue(venue, mode, start_at, end_at, guests, booking.package, extras, coupon_code)
            booking.start_at, booking.end_at, booking.venue_mode, booking.guests = start_at, end_at, mode, guests
        _apply_quote(booking, quote)
        if booking.coupon_id is None and coupon_code:
            booking.coupon = None
        refresh_payment_status(booking)
        booking.save()
        log_event(booking, _("Modified: %(old)s → %(new)s") % {"old": old_summary, "new": _summary(booking)}, actor)
        overpaid = booking.amount_paid - booking.amount_refunded - booking.total
        if overpaid > 0:
            create_refunds_for_amount(booking, overpaid, _("Booking modified to a lower total"), actor)
    audit("booking.modified", actor=actor, target=booking, before=old_summary, after=_summary(booking))
    from apps.notifications.services import notify_booking

    notify_booking("booking_modified", booking)
    return booking


def _summary(b):
    if b.kind == Booking.Kind.ROOM:
        return f"{b.check_in:%d %b}–{b.check_out:%d %b}, {b.rooms} room(s), {b.guests} guest(s), {b.total} {b.currency}"
    return f"{timezone.localtime(b.start_at):%d %b %H:%M}–{timezone.localtime(b.end_at):%H:%M}, {b.guests} guests, {b.total} {b.currency}"


def check_in_guest(booking, actor):
    if booking.status != Booking.Status.CONFIRMED:
        raise BookingError(_("Only confirmed bookings can be checked in."))
    booking.checked_in_at = timezone.now()
    booking.save(update_fields=["checked_in_at", "updated_at"])
    log_event(booking, _("Guest checked in"), actor)
    return booking


def complete_booking(booking, actor=None):
    if booking.status != Booking.Status.CONFIRMED:
        raise BookingError(_("Only confirmed bookings can be completed."))
    booking.status = Booking.Status.COMPLETED
    booking.completed_at = timezone.now()
    booking.save(update_fields=["status", "completed_at", "updated_at"])
    log_event(booking, _("Stay/event completed"), actor, Booking.Status.CONFIRMED, Booking.Status.COMPLETED)
    from apps.notifications.services import notify_booking

    notify_booking("review_invite", booking)
    return booking


def expire_stale_holds(now=None):
    now = now or timezone.now()
    stale = Booking.objects.filter(status=Booking.Status.PENDING, pay_later_requested=False, hold_expires_at__lte=now)
    count = 0
    for booking in stale:
        with transaction.atomic():
            b = Booking.objects.select_for_update().get(pk=booking.pk)
            if b.status != Booking.Status.PENDING or b.amount_paid > 0 or (b.hold_expires_at and b.hold_expires_at > now):
                continue
            b.status = Booking.Status.EXPIRED
            b.save(update_fields=["status", "updated_at"])
            log_event(b, _("Hold expired without payment; inventory released"), None, Booking.Status.PENDING, b.status)
            count += 1
    return count


def complete_finished_bookings(now=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    done = 0
    rooms = Booking.objects.filter(status=Booking.Status.CONFIRMED, kind=Booking.Kind.ROOM, check_out__lte=today)
    venues = Booking.objects.filter(status=Booking.Status.CONFIRMED, kind=Booking.Kind.VENUE, end_at__lte=now)
    for b in list(rooms) + list(venues):
        complete_booking(b)
        done += 1
    return done

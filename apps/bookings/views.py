from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.ratelimit import ratelimit
from apps.payments.providers import ProviderError, available_providers
from apps.payments.services import PaymentError, payment_options, start_payment
from apps.properties.models import RoomType, Venue
from apps.public.views import parse_date

from . import services
from .forms import (
    CancelForm,
    ModifyRoomForm,
    ModifyVenueForm,
    RoomBookingForm,
    VenueBookingForm,
)
from .models import Booking


def _require_verified(request):
    if not request.user.is_email_verified:
        messages.warning(request, _("Please confirm your email address before booking. We've sent you a link."))
        return redirect("accounts:verify_sent")
    if request.user.is_vendor_user or request.user.is_platform_admin:
        messages.warning(request, _("Partner and admin accounts can't make guest bookings. Sign in with a guest account."))
        return redirect("public:home")
    return None


def _guest_initial(user):
    return {"guest_name": user.get_full_name(), "guest_email": user.email, "guest_phone": user.phone}


@login_required
@ratelimit("book", "30/h")
def book_room(request, room_type_id):
    room = get_object_or_404(RoomType.objects.select_related("property__vendor"), pk=room_type_id, is_active=True)
    if not room.property.is_public:
        raise Http404
    blocked = _require_verified(request)
    if blocked:
        return blocked
    g = request.GET
    today = timezone.localdate()
    initial = {
        **_guest_initial(request.user),
        "check_in": parse_date(g.get("check_in")) or today + timedelta(days=1),
        "check_out": parse_date(g.get("check_out")) or today + timedelta(days=2),
        "adults": g.get("guests") or min(2, room.max_adults), "children": 0, "rooms": 1,
    }
    form = RoomBookingForm(request.POST or None, initial=initial, room_type=room)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            booking = services.create_room_booking(
                customer=request.user, room_type_id=room.pk, check_in=d["check_in"], check_out=d["check_out"], rooms=d["rooms"],
                adults=d["adults"], children=d["children"],
                guest=services.GuestDetails(d["guest_name"], d["guest_email"], d["guest_phone"], d.get("special_requests", "")),
                coupon_code=d.get("coupon_code", ""), pay_later=d.get("pay_later", False),
            )
        except services.BookingError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("Your room is held. Complete payment to confirm.") if not booking.pay_later_requested
                             else _("Request sent. The property will confirm shortly."))
            return redirect(booking.get_absolute_url())
    return render(request, "bookings/book_room.html", {"room": room, "p": room.property, "form": form})


@login_required
@ratelimit("book", "30/h")
def book_venue(request, venue_id):
    venue = get_object_or_404(Venue.objects.select_related("property__vendor"), pk=venue_id, is_active=True)
    if not venue.property.is_public:
        raise Http404
    blocked = _require_verified(request)
    if blocked:
        return blocked
    today = timezone.localdate()
    initial = {**_guest_initial(request.user), "day": parse_date(request.GET.get("date")) or today + timedelta(days=7),
               "guests": request.GET.get("guests") or min(50, venue.max_capacity), "hours": venue.min_hours}
    form = VenueBookingForm(request.POST or None, initial=initial, venue=venue)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            booking = services.create_venue_booking(
                customer=request.user, venue_id=venue.pk, day=d["day"], mode=d["mode"], start_time=d.get("start_time"),
                hours=d.get("hours"), guests=d["guests"], package_id=int(d["package"]) if d.get("package") else None,
                extras=form.extras(), event_type=d.get("event_type", ""),
                guest=services.GuestDetails(d["guest_name"], d["guest_email"], d["guest_phone"], d.get("special_requests", "")),
                coupon_code=d.get("coupon_code", ""), pay_later=d.get("pay_later", False),
            )
        except services.BookingError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("Your date is held. Complete payment to confirm.") if not booking.pay_later_requested
                             else _("Request sent. The venue will confirm shortly."))
            return redirect(booking.get_absolute_url())
    return render(request, "bookings/book_venue.html", {"venue": venue, "p": venue.property, "form": form})


@login_required
def my_bookings(request):
    tab = request.GET.get("tab", "upcoming")
    qs = request.user.bookings.select_related("property", "room_type", "venue").prefetch_related("property__images")
    today = timezone.localdate()
    now = timezone.now()
    if tab == "past":
        qs = qs.filter(Q(status=Booking.Status.COMPLETED) | Q(status=Booking.Status.CONFIRMED, check_out__lt=today) |
                       Q(status=Booking.Status.CONFIRMED, end_at__lt=now))
    elif tab == "cancelled":
        qs = qs.filter(status__in=[Booking.Status.CANCELLED, Booking.Status.REFUNDED, Booking.Status.EXPIRED])
    else:
        tab = "upcoming"
        qs = qs.filter(status__in=[Booking.Status.PENDING, Booking.Status.CONFIRMED]).filter(
            Q(check_out__gte=today) | Q(end_at__gte=now))
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    return render(request, "bookings/my_bookings.html", {"page": page, "tab": tab})


def _customer_booking(request, reference):
    return get_object_or_404(
        Booking.objects.select_related("property__vendor", "room_type", "venue", "package", "coupon"),
        reference=reference, customer=request.user,
    )


@login_required
def booking_detail(request, reference):
    booking = _customer_booking(request, reference)
    if booking.status == Booking.Status.PENDING and not booking.is_active_hold and booking.amount_paid == 0:
        services.expire_stale_holds()
        booking.refresh_from_db()
    return render(request, "bookings/detail.html", {
        "b": booking, "options": payment_options(booking), "providers": available_providers(),
        "events": booking.events.all(), "payments": booking.payments.all(), "refunds": booking.refunds.all(),
        "can_cancel": booking.status in (Booking.Status.PENDING, Booking.Status.CONFIRMED) and services.hours_until_start(booking) > 0,
        "can_modify": booking.status in (Booking.Status.PENDING, Booking.Status.CONFIRMED) and booking.property.allow_modifications
        and services.hours_until_start(booking) >= 24,
        "can_review": booking.status == Booking.Status.COMPLETED and not hasattr(booking, "review"),
        "hold_seconds": int((booking.hold_expires_at - timezone.now()).total_seconds()) if booking.hold_expires_at and booking.status == "pending" else 0,
    })


@login_required
@require_POST
@ratelimit("pay", "30/h")
def pay(request, reference):
    booking = _customer_booking(request, reference)
    option = request.POST.get("option", "full")
    provider = request.POST.get("provider", "")
    try:
        payment = start_payment(booking, option=option, provider_code=provider, customer=request.user,
                                base_url=request.build_absolute_uri("/"))
    except PaymentError as exc:
        messages.error(request, str(exc))
        return redirect(booking.get_absolute_url())
    except ProviderError:
        messages.error(request, _("That payment method is not available right now. Choose another."))
        return redirect(booking.get_absolute_url())
    return redirect(payment.checkout_url)


@login_required
def cancel(request, reference):
    booking = _customer_booking(request, reference)
    preview = services.cancellation_preview(booking)
    form = CancelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.cancel_booking(booking, request.user, form.cleaned_data.get("reason", ""))
        except services.BookingError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Booking cancelled.") + (" " + _("Your refund of %(a)s RWF is being processed.") % {"a": f"{preview['amount']:,.0f}"} if preview["amount"] else ""))
        return redirect(booking.get_absolute_url())
    return render(request, "bookings/cancel.html", {"b": booking, "preview": preview, "form": form})


@login_required
def modify(request, reference):
    booking = _customer_booking(request, reference)
    if booking.kind == Booking.Kind.ROOM:
        initial = {"check_in": booking.check_in, "check_out": booking.check_out, "rooms": booking.rooms, "adults": booking.adults, "children": booking.children}
        form = ModifyRoomForm(request.POST or None, initial=initial)
    else:
        start = timezone.localtime(booking.start_at)
        initial = {"day": start.date(), "mode": booking.venue_mode, "start_time": start.time(), "hours": int(booking.hours), "guests": booking.guests}
        form = ModifyVenueForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            services.modify_booking(booking, request.user, **form.cleaned_data)
        except services.BookingError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, _("Booking updated."))
            return redirect(booking.get_absolute_url())
    return render(request, "bookings/modify.html", {"b": booking, "form": form})


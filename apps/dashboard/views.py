import calendar as pycal
from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.bookings import services as booking_services
from apps.bookings.availability import room_availability
from apps.bookings.models import Booking, Coupon
from apps.core.audit import audit
from apps.core.rbac import vendor_required
from apps.notifications.services import send_email, send_staff_invite
from apps.payments import services as pay
from apps.payments.models import LedgerEntry
from apps.properties.models import (
    Inquiry,
    Property,
    PropertyImage,
    RoomBlock,
    RoomImage,
    RoomType,
    SeasonalRate,
    Venue,
    VenueBlock,
    VenueExtra,
    VenueImage,
    VenuePackage,
)
from apps.reports import services as reports
from apps.reviews.models import Review
from apps.vendors.forms import (
    InviteForm,
    MembershipForm,
    PayoutDetailsForm,
    VendorProfileForm,
)
from apps.vendors.models import StaffInvite, StaffMembership

from .forms import (
    CouponForm,
    ImagesForm,
    OfflinePaymentForm,
    PayoutRequestForm,
    PolicyForm,
    PropertyForm,
    ReplyForm,
    RoomBlockForm,
    RoomTypeForm,
    SeasonalRateForm,
    VendorCancelForm,
    VenueBlockForm,
    VenueExtraForm,
    VenueForm,
    VenuePackageForm,
)


def form_page(request, form, title, back, subtitle="", submit=None, multipart=False, extra=None):
    ctx = {"form": form, "title": title, "back": back, "subtitle": subtitle, "submit": submit or _("Save"), "multipart": multipart}
    ctx.update(extra or {})
    return render(request, "dashboard/form_page.html", ctx)


# --- Overview ------------------------------------------------------------------

@vendor_required()
def overview(request):
    ctx = request.vctx
    today = timezone.localdate()
    bookings = ctx.bookings().select_related("property", "room_type", "venue")
    month_start = today.replace(day=1)
    upcoming = bookings.filter(status=Booking.Status.CONFIRMED).filter(
        Q(check_in__gte=today) | Q(start_at__date__gte=today)).order_by("check_in", "start_at")[:8]
    arrivals = bookings.filter(status=Booking.Status.CONFIRMED).filter(Q(check_in=today) | Q(start_at__date=today))
    pending = bookings.filter(status=Booking.Status.PENDING, pay_later_requested=True)
    summary = reports.summary(reports.Scope(ctx.vendor, ctx.property_ids()), month_start, today)
    wallet = pay.get_wallet(ctx.vendor) if ctx.can("finance") else None
    from apps.vendors.views import onboarding_state

    steps, ready = onboarding_state(ctx.vendor)
    return render(request, "dashboard/overview.html", {
        "upcoming": upcoming, "arrivals": arrivals, "pay_later": pending, "summary": summary, "wallet": wallet,
        "available": pay.available_balance(ctx.vendor) if wallet else None,
        "properties": ctx.properties(), "steps": steps, "ready": ready,
        "pending_reviews": Review.objects.filter(property_id__in=ctx.property_ids(), status="approved", vendor_reply="").count(),
        "open_inquiries": Inquiry.objects.filter(property_id__in=ctx.property_ids(), is_resolved=False).count(),
        "recent": bookings[:6],
    })


# --- Properties ----------------------------------------------------------------

@vendor_required("listings")
def property_list(request):
    props = request.vctx.properties().prefetch_related("images").order_by("name")
    return render(request, "dashboard/properties.html", {"properties": props})


@vendor_required("listings")
def property_create(request):
    if not request.vctx.is_owner:
        messages.error(request, _("Only the business owner can add properties."))
        return redirect("dashboard:properties")
    form = PropertyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        prop = form.save(commit=False)
        prop.vendor = request.vctx.vendor
        prop.status = Property.Status.DRAFT
        prop.save()
        form.save_m2m()
        audit("property.created", request=request, target=prop)
        messages.success(request, _("Property created. Add photos, rooms or venues, then submit it for verification."))
        return redirect("dashboard:property_edit", pk=prop.pk)
    return form_page(request, form, _("Add a property"), reverse("dashboard:properties"), submit=_("Create property"))


@vendor_required("listings")
def property_edit(request, pk):
    prop = request.vctx.get_property(pk)
    form = PropertyForm(request.POST or None, instance=prop, prefix="d") if request.POST.get("section") in (None, "details") else PropertyForm(instance=prop, prefix="d")
    policy_form = PolicyForm(instance=prop, prefix="pol")
    if request.method == "POST":
        section = request.POST.get("section", "details")
        if section == "details" and form.is_valid():
            form.save()
            prop.refresh_starting_price()
            messages.success(request, _("Details saved."))
            return redirect(reverse("dashboard:property_edit", args=[pk]))
        if section == "policies":
            policy_form = PolicyForm(request.POST, instance=prop, prefix="pol")
            if policy_form.is_valid():
                policy_form.save()
                audit("property.policies_changed", request=request, target=prop)
                messages.success(request, _("Policies saved."))
                return redirect(reverse("dashboard:property_edit", args=[pk]) + "#policies")
    return render(request, "dashboard/property_edit.html", {
        "p": prop, "form": form, "policy_form": policy_form, "images_form": ImagesForm(),
        "rooms": prop.room_types.all(), "venues": prop.venues.all(), "images": prop.images.all(),
    })


@vendor_required("listings")
@require_POST
def property_submit(request, pk):
    prop = request.vctx.get_property(pk)
    problems = []
    if not prop.images.exists():
        problems.append(_("add at least one photo"))
    if not prop.room_types.filter(is_active=True).exists() and not prop.venues.filter(is_active=True).exists():
        problems.append(_("add a room type or a venue"))
    if prop.latitude is None or prop.longitude is None:
        problems.append(_("set the map location"))
    if problems:
        messages.error(request, _("Before submitting, please %(p)s.") % {"p": ", ".join(str(p) for p in problems)})
    elif prop.status in (Property.Status.DRAFT, Property.Status.REJECTED):
        prop.status = Property.Status.PENDING
        prop.save(update_fields=["status", "updated_at"])
        audit("property.submitted", request=request, target=prop)
        from apps.notifications.services import notify_admins

        notify_admins("property_submitted", _("Property awaiting verification: %(p)s") % {"p": prop}, reverse("adminpanel:property_detail", args=[prop.pk]))
        messages.success(request, _("Submitted for verification."))
        if not request.vctx.vendor.is_approved:
            messages.info(request, _("It goes live once your business and this property are both approved."))
    else:
        messages.info(request, _("This property is already %(s)s.") % {"s": prop.get_status_display().lower()})
    return redirect("dashboard:property_edit", pk=pk)


def _save_images(files, model, **fk):
    start = model.objects.filter(**fk).count()
    for i, f in enumerate(files):
        model.objects.create(image=f, sort_order=start + i, **fk)


@vendor_required("listings")
@require_POST
def property_images(request, pk):
    prop = request.vctx.get_property(pk)
    form = ImagesForm(request.POST, request.FILES)
    if form.is_valid():
        _save_images(form.cleaned_data["images"], PropertyImage, property=prop)
        messages.success(request, _("Photos uploaded."))
    else:
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(reverse("dashboard:property_edit", args=[pk]) + "#photos")


@vendor_required("listings")
@require_POST
def image_action(request, kind, image_id):
    model = {"property": PropertyImage, "room": RoomImage, "venue": VenueImage}.get(kind)
    if model is None:
        raise Http404
    img = get_object_or_404(model, pk=image_id)
    owner_prop = img.property if kind == "property" else (img.room_type.property if kind == "room" else img.venue.property)
    request.vctx.get_property(owner_prop.pk)
    if request.POST.get("action") == "cover":
        fk = {"property": owner_prop} if kind == "property" else ({"room_type": img.room_type} if kind == "room" else {"venue": img.venue})
        model.objects.filter(**fk).exclude(pk=img.pk).update(sort_order=1)
        img.sort_order = 0
        img.save(update_fields=["sort_order"])
        messages.success(request, _("Cover photo updated."))
    else:
        img.image.delete(save=False)
        img.delete()
        messages.success(request, _("Photo deleted."))
    nxt = request.POST.get("next", "")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = reverse("dashboard:property_edit", args=[owner_prop.pk])
    return redirect(nxt)


# --- Rooms ---------------------------------------------------------------------

def _room(request, pk, perm="listings"):
    room = get_object_or_404(RoomType.objects.select_related("property"), pk=pk)
    request.vctx.get_property(room.property_id)
    return room


@vendor_required("listings")
def room_create(request, pk):
    prop = request.vctx.get_property(pk)
    form = RoomTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        room = form.save(commit=False)
        room.property = prop
        room.save()
        form.save_m2m()
        messages.success(request, _("Room type added. Add photos and seasonal prices next."))
        return redirect("dashboard:room_edit", pk=room.pk)
    return form_page(request, form, _("Add room type · %(p)s") % {"p": prop.name}, reverse("dashboard:property_edit", args=[pk]) + "#rooms")


@vendor_required("listings")
def room_edit(request, pk):
    room = _room(request, pk)
    can_price = request.vctx.can("pricing")
    form = RoomTypeForm(request.POST or None, instance=room, prefix="r")
    rate_form = SeasonalRateForm(prefix="s")
    block_form = RoomBlockForm(prefix="b", room_type=room)
    if request.method == "POST":
        section = request.POST.get("section")
        if section == "details" and form.is_valid():
            form.save()
            messages.success(request, _("Room saved."))
            return redirect("dashboard:room_edit", pk=pk)
        if section == "rate" and can_price:
            rate_form = SeasonalRateForm(request.POST, prefix="s")
            if rate_form.is_valid():
                rate = rate_form.save(commit=False)
                rate.room_type = room
                rate.save()
                audit("pricing.seasonal_added", request=request, target=room, name=rate.name, price=str(rate.nightly_price))
                messages.success(request, _("Seasonal price added."))
                return redirect(reverse("dashboard:room_edit", args=[pk]) + "#rates")
        if section == "block":
            block_form = RoomBlockForm(request.POST, prefix="b", room_type=room)
            if block_form.is_valid():
                block = block_form.save(commit=False)
                block.room_type = room
                block.created_by = request.user
                block.save()
                messages.success(request, _("Dates closed."))
                return redirect(reverse("dashboard:room_edit", args=[pk]) + "#blocks")
        if section == "images":
            img_form = ImagesForm(request.POST, request.FILES)
            if img_form.is_valid():
                _save_images(img_form.cleaned_data["images"], RoomImage, room_type=room)
                messages.success(request, _("Photos uploaded."))
            else:
                messages.error(request, "; ".join(e for errs in img_form.errors.values() for e in errs))
            return redirect(reverse("dashboard:room_edit", args=[pk]) + "#photos")
    return render(request, "dashboard/room_edit.html", {
        "room": room, "p": room.property, "form": form, "rate_form": rate_form, "block_form": block_form,
        "images_form": ImagesForm(), "rates": room.seasonal_rates.all(), "blocks": room.blocks.filter(end_date__gte=timezone.localdate()),
        "can_price": can_price,
    })


@vendor_required("listings")
@require_POST
def room_child_delete(request, kind, pk):
    model = {"rate": SeasonalRate, "block": RoomBlock}.get(kind)
    if model is None:
        raise Http404
    obj = get_object_or_404(model.objects.select_related("room_type"), pk=pk)
    request.vctx.get_property(obj.room_type.property_id)
    room_pk = obj.room_type_id
    obj.delete()
    messages.success(request, _("Removed."))
    return redirect("dashboard:room_edit", pk=room_pk)


# --- Venues --------------------------------------------------------------------

def _venue(request, pk):
    venue = get_object_or_404(Venue.objects.select_related("property"), pk=pk)
    request.vctx.get_property(venue.property_id)
    return venue


@vendor_required("listings")
def venue_create(request, pk):
    prop = request.vctx.get_property(pk)
    form = VenueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        venue = form.save(commit=False)
        venue.property = prop
        venue.save()
        form.save_m2m()
        messages.success(request, _("Venue added. Add packages, extras and photos next."))
        return redirect("dashboard:venue_edit", pk=venue.pk)
    return form_page(request, form, _("Add event space · %(p)s") % {"p": prop.name}, reverse("dashboard:property_edit", args=[pk]) + "#venues")


@vendor_required("listings")
def venue_edit(request, pk):
    venue = _venue(request, pk)
    form = VenueForm(request.POST or None, instance=venue, prefix="v")
    package_form, extra_form, block_form = VenuePackageForm(prefix="pk"), VenueExtraForm(prefix="ex"), VenueBlockForm(prefix="bl")
    if request.method == "POST":
        section = request.POST.get("section")
        target = {"package": (VenuePackageForm, "pk"), "extra": (VenueExtraForm, "ex"), "block": (VenueBlockForm, "bl")}
        if section == "details" and form.is_valid():
            form.save()
            messages.success(request, _("Venue saved."))
            return redirect("dashboard:venue_edit", pk=pk)
        if section in target:
            cls, prefix = target[section]
            bound = cls(request.POST, prefix=prefix)
            if bound.is_valid():
                obj = bound.save(commit=False)
                obj.venue = venue
                if section == "block":
                    obj.created_by = request.user
                obj.save()
                messages.success(request, _("Saved."))
                return redirect(reverse("dashboard:venue_edit", args=[pk]) + f"#{section}s")
            package_form = bound if section == "package" else package_form
            extra_form = bound if section == "extra" else extra_form
            block_form = bound if section == "block" else block_form
        if section == "images":
            img_form = ImagesForm(request.POST, request.FILES)
            if img_form.is_valid():
                _save_images(img_form.cleaned_data["images"], VenueImage, venue=venue)
                messages.success(request, _("Photos uploaded."))
            else:
                messages.error(request, "; ".join(e for errs in img_form.errors.values() for e in errs))
            return redirect(reverse("dashboard:venue_edit", args=[pk]) + "#photos")
    return render(request, "dashboard/venue_edit.html", {
        "venue": venue, "p": venue.property, "form": form, "package_form": package_form, "extra_form": extra_form,
        "block_form": block_form, "images_form": ImagesForm(), "blocks": venue.blocks.filter(end_at__gte=timezone.now()),
    })


@vendor_required("listings")
@require_POST
def venue_child_delete(request, kind, pk):
    model = {"package": VenuePackage, "extra": VenueExtra, "block": VenueBlock}.get(kind)
    if model is None:
        raise Http404
    obj = get_object_or_404(model.objects.select_related("venue"), pk=pk)
    request.vctx.get_property(obj.venue.property_id)
    venue_pk = obj.venue_id
    obj.delete()
    messages.success(request, _("Removed."))
    return redirect("dashboard:venue_edit", pk=venue_pk)


# --- Calendar ------------------------------------------------------------------

@vendor_required("availability_view")
def calendar_view(request):
    ctx = request.vctx
    rooms = RoomType.objects.filter(property__in=ctx.properties()).select_related("property")
    venues = Venue.objects.filter(property__in=ctx.properties()).select_related("property")
    today = timezone.localdate()
    try:
        month = date.fromisoformat(request.GET.get("month", "") + "-01") if request.GET.get("month") else today.replace(day=1)
    except ValueError:
        month = today.replace(day=1)
    days_in_month = pycal.monthrange(month.year, month.month)[1]
    month_end = month + timedelta(days=days_in_month)
    sel = request.GET.get("item", "")
    weeks, selected, kind = [], None, ""
    if sel.startswith("room-"):
        selected = rooms.filter(pk=sel[5:]).first() if sel[5:].isdigit() else None
        kind = "room"
    elif sel.startswith("venue-"):
        selected = venues.filter(pk=sel[6:]).first() if sel[6:].isdigit() else None
        kind = "venue"
    if selected is None and rooms.exists():
        selected, kind = rooms.first(), "room"
    elif selected is None and venues.exists():
        selected, kind = venues.first(), "venue"
    cells = {}
    if kind == "room" and selected:
        avail = room_availability(selected, month, month_end)
        bookings = Booking.objects.holding_inventory().filter(room_type=selected, check_in__lt=month_end, check_out__gt=month)
        for d, free in avail.items():
            cells[d] = {"free": free, "total": selected.quantity,
                        "bookings": [b for b in bookings if b.check_in <= d < b.check_out]}
    elif kind == "venue" and selected:
        bookings = list(Booking.objects.holding_inventory().filter(venue=selected, start_at__date__lt=month_end, start_at__date__gte=month))
        blocks = list(selected.blocks.filter(start_at__date__lt=month_end, end_at__date__gte=month))
        for i in range(days_in_month):
            d = month + timedelta(days=i)
            day_b = [b for b in bookings if timezone.localtime(b.start_at).date() == d]
            day_blk = [b for b in blocks if timezone.localtime(b.start_at).date() <= d <= timezone.localtime(b.end_at).date()]
            cells[d] = {"bookings": day_b, "blocked": bool(day_blk), "free": 0 if (day_b or day_blk) else 1, "total": 1}
    for week in pycal.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month):
        weeks.append([{"date": d, "in_month": d.month == month.month, "cell": cells.get(d), "past": d < today} for d in week])
    prev_month = (month - timedelta(days=1)).replace(day=1)
    return render(request, "dashboard/calendar.html", {
        "rooms": rooms, "venues": venues, "selected": selected, "kind": kind, "weeks": weeks, "month": month,
        "prev": prev_month.strftime("%Y-%m"), "next": month_end.strftime("%Y-%m"), "sel": f"{kind}-{selected.pk}" if selected else "",
        "can_block": ctx.can("availability"),
    })


# --- Bookings ------------------------------------------------------------------

@vendor_required("bookings")
def booking_list(request):
    ctx = request.vctx
    qs = ctx.bookings().select_related("property", "room_type", "venue", "customer")
    g = request.GET
    if g.get("status"):
        qs = qs.filter(status=g["status"])
    if g.get("property") and g["property"].isdigit():
        qs = qs.filter(property_id=int(g["property"]))
    if g.get("q"):
        q = g["q"].strip()[:60]
        qs = qs.filter(Q(reference__icontains=q) | Q(guest_name__icontains=q) | Q(guest_email__icontains=q) | Q(guest_phone__icontains=q))
    if g.get("when") == "today":
        today = timezone.localdate()
        qs = qs.filter(Q(check_in=today) | Q(start_at__date=today))
    elif g.get("when") == "upcoming":
        today = timezone.localdate()
        qs = qs.filter(Q(check_in__gte=today) | Q(start_at__date__gte=today))
    if g.get("export") == "csv" and ctx.can("reports"):
        start, end = reports.parse_range(request, 365)
        return reports.csv_response("bookings", reports.Scope(ctx.vendor, ctx.property_ids()), start, end, prefix=ctx.vendor.slug)
    page = Paginator(qs, 25).get_page(g.get("page"))
    return render(request, "dashboard/bookings.html", {"page": page, "statuses": Booking.Status.choices, "properties": ctx.properties()})


def _vendor_booking(request, reference):
    return get_object_or_404(request.vctx.bookings().select_related("property", "room_type", "venue", "customer", "package"), reference=reference)


@vendor_required("bookings")
def booking_detail(request, reference):
    b = _vendor_booking(request, reference)
    return render(request, "dashboard/booking_detail.html", {
        "b": b, "events": b.events.select_related("actor"), "payments": b.payments.all(), "refunds": b.refunds.all(),
        "offline_form": OfflinePaymentForm(initial={"amount": int(b.balance_due)}), "cancel_form": VendorCancelForm(),
        "preview": booking_services.cancellation_preview(b, by_vendor=True), "can_offline": request.vctx.can("offline_payments"),
    })


@vendor_required("bookings")
@require_POST
def booking_action(request, reference, action):
    b = _vendor_booking(request, reference)
    try:
        if action == "approve_pay_later":
            booking_services.approve_pay_later(b, request.user)
            messages.success(request, _("Approved. The guest has been notified."))
        elif action == "decline_pay_later":
            booking_services.decline_pay_later(b, request.user, request.POST.get("reason", ""))
            messages.success(request, _("Declined. The guest can still pay online during the hold."))
        elif action == "check_in":
            booking_services.check_in_guest(b, request.user)
            messages.success(request, _("Guest checked in."))
        elif action == "complete":
            booking_services.complete_booking(b, request.user)
            messages.success(request, _("Marked as completed. The guest was invited to review."))
        elif action == "cancel":
            form = VendorCancelForm(request.POST)
            if not form.is_valid():
                messages.error(request, _("Give the guest a reason for cancelling."))
            else:
                booking_services.cancel_booking(b, request.user, form.cleaned_data["reason"], by_vendor=True)
                messages.success(request, _("Booking cancelled; any payment will be refunded in full after Heza approval."))
        elif action == "offline_payment":
            if not request.vctx.can("offline_payments"):
                raise Http404
            form = OfflinePaymentForm(request.POST)
            if form.is_valid():
                pay.record_offline_payment(b, form.cleaned_data["amount"], form.cleaned_data["method"], request.user, form.cleaned_data.get("note", ""))
                messages.success(request, _("Payment recorded."))
            else:
                messages.error(request, _("Enter a valid amount and method."))
        else:
            raise Http404
    except (booking_services.BookingError, pay.PaymentError) as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:booking_detail", reference=reference)


# --- Finance -------------------------------------------------------------------

@vendor_required("finance")
def wallet(request):
    vendor = request.vctx.vendor
    w = pay.get_wallet(vendor)
    entries = Paginator(LedgerEntry.objects.filter(wallet=w).select_related("booking"), 25).get_page(request.GET.get("page"))
    form = PayoutRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            pay.request_payout(vendor, form.cleaned_data["amount"], request.user)
        except pay.PaymentError as exc:
            form.add_error("amount", str(exc))
        else:
            messages.success(request, _("Payout requested. Heza reviews payouts every business day."))
            return redirect("dashboard:wallet")
    totals = LedgerEntry.objects.filter(wallet=w).values("entry_type").annotate(t=Sum("amount"))
    return render(request, "dashboard/wallet.html", {
        "wallet": w, "available": pay.available_balance(vendor), "entries": entries, "form": form,
        "payouts": vendor.payouts.all()[:20], "totals": {t["entry_type"]: t["t"] for t in totals},
        "reserved": pay.reserved_for_payouts(vendor),
    })


# --- Staff ---------------------------------------------------------------------

@vendor_required("staff")
def staff(request):
    vendor = request.vctx.vendor
    form = InviteForm(request.POST or None, vendor=vendor)
    if request.method == "POST" and form.is_valid():
        invite = form.save(commit=False)
        invite.vendor = vendor
        invite.invited_by = request.user
        invite.save()
        form.save_m2m()
        send_staff_invite(invite)
        audit("staff.invited", request=request, target=vendor, email=invite.email, role=invite.role)
        messages.success(request, _("Invitation sent to %(e)s.") % {"e": invite.email})
        return redirect("dashboard:staff")
    return render(request, "dashboard/staff.html", {
        "form": form, "members": vendor.memberships.select_related("user").prefetch_related("properties"),
        "invites": vendor.invites.filter(accepted_at__isnull=True, revoked=False),
    })


@vendor_required("staff")
def staff_edit(request, pk):
    m = get_object_or_404(StaffMembership, pk=pk, vendor=request.vctx.vendor)
    form = MembershipForm(request.POST or None, instance=m)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            m.user.role = m.role
            m.user.save(update_fields=["role"])
        audit("staff.updated", request=request, target=m, role=m.role, active=m.is_active)
        messages.success(request, _("Team member updated."))
        return redirect("dashboard:staff")
    return form_page(request, form, _("Edit access · %(u)s") % {"u": m.user}, reverse("dashboard:staff"))


@vendor_required("staff")
@require_POST
def invite_action(request, pk, action):
    invite = get_object_or_404(StaffInvite, pk=pk, vendor=request.vctx.vendor)
    if action == "revoke":
        invite.revoked = True
        invite.save(update_fields=["revoked"])
        messages.success(request, _("Invitation revoked."))
    elif action == "resend":
        invite.expires_at = timezone.now() + timedelta(days=7)
        invite.save(update_fields=["expires_at"])
        send_staff_invite(invite)
        messages.success(request, _("Invitation re-sent."))
    return redirect("dashboard:staff")


# --- Reviews & inquiries ------------------------------------------------------

@vendor_required("reviews")
def reviews(request):
    qs = Review.objects.filter(property_id__in=request.vctx.property_ids()).exclude(status="rejected").select_related("property", "author")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "dashboard/reviews.html", {"page": page, "form": ReplyForm()})


@vendor_required("reviews")
@require_POST
def review_reply(request, pk):
    review = get_object_or_404(Review, pk=pk, property_id__in=request.vctx.property_ids())
    form = ReplyForm(request.POST)
    if form.is_valid():
        review.vendor_reply = form.cleaned_data["reply"]
        review.vendor_replied_at = timezone.now()
        review.save(update_fields=["vendor_reply", "vendor_replied_at", "updated_at"])
        messages.success(request, _("Reply published."))
    return redirect("dashboard:reviews")


@vendor_required("inquiries")
def inquiries(request):
    qs = Inquiry.objects.filter(property_id__in=request.vctx.property_ids()).select_related("property")
    if request.GET.get("show") != "all":
        qs = qs.filter(is_resolved=False)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "dashboard/inquiries.html", {"page": page, "form": ReplyForm()})


@vendor_required("inquiries")
@require_POST
def inquiry_reply(request, pk):
    inquiry = get_object_or_404(Inquiry.objects.select_related("property"), pk=pk, property_id__in=request.vctx.property_ids())
    if request.POST.get("action") == "resolve":
        inquiry.is_resolved = True
        inquiry.save(update_fields=["is_resolved", "updated_at"])
        messages.success(request, _("Marked as resolved."))
        return redirect("dashboard:inquiries")
    form = ReplyForm(request.POST)
    if form.is_valid():
        inquiry.reply = form.cleaned_data["reply"]
        inquiry.replied_at = timezone.now()
        inquiry.is_resolved = True
        inquiry.save()
        send_email(inquiry.email, _("Reply from %(p)s") % {"p": inquiry.property.name},
                   [form.cleaned_data["reply"], _("— %(p)s via Heza") % {"p": inquiry.property.name}],
                   user=inquiry.user, event="inquiry_reply", cta_url=inquiry.property.get_absolute_url(), cta_label=_("View property"),
                   greeting=_("Hello %(n)s,") % {"n": inquiry.name})
        messages.success(request, _("Reply emailed to %(e)s.") % {"e": inquiry.email})
    return redirect("dashboard:inquiries")


# --- Coupons -------------------------------------------------------------------

@vendor_required("coupons")
def coupons(request):
    vendor = request.vctx.vendor
    form = CouponForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.vendor = vendor
        c.save()
        messages.success(request, _("Promo code %(c)s created.") % {"c": c.code})
        return redirect("dashboard:coupons")
    return render(request, "dashboard/coupons.html", {"form": form, "coupons": vendor.coupons.all()})


@vendor_required("coupons")
@require_POST
def coupon_toggle(request, pk):
    c = get_object_or_404(Coupon, pk=pk, vendor=request.vctx.vendor)
    c.is_active = not c.is_active
    c.save(update_fields=["is_active", "updated_at"])
    return redirect("dashboard:coupons")


# --- Reports & settings --------------------------------------------------------

@vendor_required("reports")
def reports_view(request):
    ctx = request.vctx
    start, end = reports.parse_range(request)
    scope = reports.Scope(ctx.vendor, ctx.property_ids())
    kind = request.GET.get("download")
    if kind in reports.REPORT_KINDS:
        return reports.csv_response(kind, scope, start, end, prefix=ctx.vendor.slug)
    return render(request, "dashboard/reports.html", {
        "s": reports.summary(scope, start, end), "occupancy": reports.occupancy(scope, start, end),
        "kinds": reports.REPORT_KINDS, "start": start, "end": end,
    })


@vendor_required("settings")
def settings_view(request):
    vendor = request.vctx.vendor
    profile = VendorProfileForm(instance=vendor, prefix="p")
    payout = PayoutDetailsForm(instance=vendor, prefix="pay")
    if request.method == "POST":
        if request.POST.get("section") == "profile":
            profile = VendorProfileForm(request.POST, request.FILES, instance=vendor, prefix="p")
            if profile.is_valid():
                profile.save()
                messages.success(request, _("Business profile saved."))
                return redirect("dashboard:settings")
        elif request.POST.get("section") == "payout":
            payout = PayoutDetailsForm(request.POST, instance=vendor, prefix="pay")
            if payout.is_valid():
                payout.save()
                audit("vendor.payout_details_changed", request=request, target=vendor)
                messages.success(request, _("Payout details saved."))
                return redirect("dashboard:settings")
    return render(request, "dashboard/settings.html", {"profile": profile, "payout": payout, "vendor": vendor})


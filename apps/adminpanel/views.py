from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.bookings import services as booking_services
from apps.bookings.models import Booking, Coupon
from apps.core.audit import audit
from apps.core.forms import BootstrapMixin
from apps.core.models import AuditLog, CategoryCommission, PlatformSettings
from apps.core.rbac import admin_required
from apps.dashboard.forms import CouponForm
from apps.notifications.services import notify_vendor
from apps.payments import services as pay
from apps.payments.models import Payment, Payout, Refund, WebhookEvent
from apps.properties.models import Amenity, Category, Property
from apps.reports import services as reports
from apps.reviews.models import Review, refresh_property_rating
from apps.vendors.models import Vendor, VendorDocument


def _page(request, qs, n=25):
    return Paginator(qs, n).get_page(request.GET.get("page"))


@admin_required
def overview(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    summary = reports.summary(reports.Scope(), month_start, today)
    ctx = {
        "s": summary,
        "pending_vendors": Vendor.objects.filter(status=Vendor.Status.PENDING).count(),
        "pending_properties": Property.objects.filter(status=Property.Status.PENDING).count(),
        "pending_refunds": Refund.objects.filter(status=Refund.Status.PENDING).count(),
        "pending_payouts": Payout.objects.filter(status__in=[Payout.Status.REQUESTED, Payout.Status.APPROVED]).count(),
        "pending_reviews": Review.objects.filter(status=Review.Status.PENDING).count(),
        "bad_webhooks": WebhookEvent.objects.filter(signature_valid=False, received_at__gte=timezone.now() - timedelta(days=1)).count(),
        "vendors_active": Vendor.objects.filter(status=Vendor.Status.APPROVED).count(),
        "properties_live": Property.objects.public().count(),
        "customers": User.objects.filter(role=Role.CUSTOMER).count(),
        "platform_wallet": pay.get_wallet(None),
        "recent_bookings": Booking.objects.select_related("property")[:8],
        "recent_audit": AuditLog.objects.select_related("actor")[:10],
        "top_vendors": Booking.objects.filter(status__in=["confirmed", "completed"], created_at__date__gte=month_start)
        .values("vendor__business_name").annotate(n=Count("id"), gmv=Sum("total")).order_by("-gmv")[:5],
    }
    return render(request, "adminpanel/overview.html", ctx)


# --- Vendors -------------------------------------------------------------------

@admin_required
def vendors(request):
    qs = Vendor.objects.select_related("owner").annotate(n_props=Count("properties"))
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    if request.GET.get("q"):
        q = request.GET["q"][:60]
        qs = qs.filter(Q(business_name__icontains=q) | Q(email__icontains=q) | Q(tin__icontains=q))
    return render(request, "adminpanel/vendors.html", {"page": _page(request, qs.order_by("-submitted_at", "business_name")), "statuses": Vendor.Status.choices})


class CommissionForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["commission_rate"]


@admin_required
def vendor_detail(request, pk):
    vendor = get_object_or_404(Vendor.objects.select_related("owner"), pk=pk)
    form = CommissionForm(request.POST or None, instance=vendor)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit("vendor.commission_changed", request=request, target=vendor, rate=str(vendor.commission_rate))
        messages.success(request, _("Commission updated."))
        return redirect("adminpanel:vendor_detail", pk=pk)
    from apps.vendors.views import onboarding_state

    steps, ready = onboarding_state(vendor)
    return render(request, "adminpanel/vendor_detail.html", {
        "v": vendor, "form": form, "documents": vendor.documents.all(), "properties": vendor.properties.all(),
        "members": vendor.memberships.select_related("user"), "wallet": pay.get_wallet(vendor), "steps": steps,
        "bookings": vendor.bookings.count(),
    })


@admin_required
@require_POST
def vendor_action(request, pk, action):
    vendor = get_object_or_404(Vendor, pk=pk)
    note = request.POST.get("note", "")[:500]
    transitions = {
        "approve": Vendor.Status.APPROVED, "reject": Vendor.Status.REJECTED,
        "suspend": Vendor.Status.SUSPENDED, "reinstate": Vendor.Status.APPROVED,
    }
    if action not in transitions:
        return redirect("adminpanel:vendor_detail", pk=pk)
    if action in ("reject", "suspend") and not note:
        messages.error(request, _("Add a note explaining the decision; the vendor will see it."))
        return redirect("adminpanel:vendor_detail", pk=pk)
    vendor.status = transitions[action]
    vendor.review_note = note
    vendor.reviewed_at = timezone.now()
    vendor.reviewed_by = request.user
    vendor.save()
    audit(f"vendor.{action}", request=request, target=vendor, description=note)
    subject = {
        "approve": _("Your business is approved on Heza"), "reject": _("Your Heza application needs changes"),
        "suspend": _("Your Heza account is suspended"), "reinstate": _("Your Heza account is active again"),
    }[action]
    notify_vendor(vendor, f"vendor_{action}", subject, note or _("Submitted properties go live once each one is verified."))
    messages.success(request, _("Vendor %(a)s.") % {"a": vendor.get_status_display().lower()})
    return redirect("adminpanel:vendor_detail", pk=pk)


@admin_required
@require_POST
def document_action(request, pk, action):
    doc = get_object_or_404(VendorDocument, pk=pk)
    if action in ("accept", "reject"):
        doc.status = VendorDocument.Status.ACCEPTED if action == "accept" else VendorDocument.Status.REJECTED
        doc.note = request.POST.get("note", "")[:255]
        doc.save(update_fields=["status", "note", "updated_at"])
        audit(f"vendor.document_{action}", request=request, target=doc)
    return redirect("adminpanel:vendor_detail", pk=doc.vendor_id)


# --- Properties ----------------------------------------------------------------

@admin_required
def properties(request):
    qs = Property.objects.select_related("vendor").annotate(n_rooms=Count("room_types", distinct=True), n_venues=Count("venues", distinct=True))
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("q"):
        q = request.GET["q"][:60]
        qs = qs.filter(Q(name__icontains=q) | Q(city__icontains=q) | Q(vendor__business_name__icontains=q))
    return render(request, "adminpanel/properties.html", {"page": _page(request, qs.order_by("status", "name")), "statuses": Property.Status.choices})


@admin_required
def property_detail(request, pk):
    prop = get_object_or_404(Property.objects.select_related("vendor"), pk=pk)
    return render(request, "adminpanel/property_detail.html", {
        "p": prop, "rooms": prop.room_types.all(), "venues": prop.venues.all(), "images": prop.images.all(),
        "bookings": prop.bookings.count(),
    })


@admin_required
@require_POST
def property_action(request, pk, action):
    prop = get_object_or_404(Property.objects.select_related("vendor"), pk=pk)
    note = request.POST.get("note", "")[:500]
    if action == "feature":
        prop.is_featured = not prop.is_featured
        prop.save(update_fields=["is_featured", "updated_at"])
        audit("property.featured" if prop.is_featured else "property.unfeatured", request=request, target=prop)
        return redirect("adminpanel:property_detail", pk=pk)
    transitions = {"verify": Property.Status.VERIFIED, "reject": Property.Status.REJECTED, "suspend": Property.Status.SUSPENDED,
                   "reinstate": Property.Status.VERIFIED}
    if action not in transitions:
        return redirect("adminpanel:property_detail", pk=pk)
    if action in ("reject", "suspend") and not note:
        messages.error(request, _("Add a note for the vendor."))
        return redirect("adminpanel:property_detail", pk=pk)
    prop.status = transitions[action]
    prop.review_note = note
    prop.save(update_fields=["status", "review_note", "updated_at"])
    audit(f"property.{action}", request=request, target=prop, description=note)
    notify_vendor(prop.vendor, f"property_{action}", _("%(p)s is now %(s)s") % {"p": prop.name, "s": prop.get_status_display().lower()}, note,
                  link=reverse("dashboard:property_edit", args=[prop.pk]))
    if action == "verify" and not prop.vendor.is_approved:
        messages.warning(request, _("Verified, but it stays hidden until the vendor is approved."))
    messages.success(request, _("Property %(s)s.") % {"s": prop.get_status_display().lower()})
    return redirect("adminpanel:property_detail", pk=pk)


# --- Users ---------------------------------------------------------------------

@admin_required
def users(request):
    qs = User.objects.all()
    if request.GET.get("role"):
        qs = qs.filter(role=request.GET["role"])
    if request.GET.get("q"):
        q = request.GET["q"][:60]
        qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone__icontains=q))
    if request.GET.get("suspended"):
        qs = qs.filter(is_suspended=True)
    return render(request, "adminpanel/users.html", {"page": _page(request, qs), "roles": Role.choices})


@admin_required
@require_POST
def user_action(request, pk, action):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, _("You can't change your own account here."))
        return redirect("adminpanel:users")
    if action == "suspend":
        reason = request.POST.get("note", "")[:255]
        if not reason:
            messages.error(request, _("Give a reason for the suspension."))
            return redirect("adminpanel:users")
        user.suspend(reason)
        from django.contrib.sessions.models import Session

        for s in Session.objects.filter(expire_date__gt=timezone.now()):
            if s.get_decoded().get("_auth_user_id") == str(user.pk):
                s.delete()
        audit("user.suspended", request=request, target=user, description=reason)
        messages.success(request, _("%(u)s suspended and signed out.") % {"u": user})
    elif action == "reinstate":
        user.reinstate()
        audit("user.reinstated", request=request, target=user)
        messages.success(request, _("%(u)s reinstated.") % {"u": user})
    elif action == "verify_email":
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])
        audit("user.email_verified_by_admin", request=request, target=user)
        messages.success(request, _("Email marked as verified."))
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "adminpanel:users")


# --- Bookings & money ----------------------------------------------------------

@admin_required
def bookings(request):
    qs = Booking.objects.select_related("property", "vendor", "customer")
    g = request.GET
    if g.get("status"):
        qs = qs.filter(status=g["status"])
    if g.get("q"):
        q = g["q"][:60]
        qs = qs.filter(Q(reference__icontains=q) | Q(guest_name__icontains=q) | Q(guest_email__icontains=q) | Q(property__name__icontains=q))
    return render(request, "adminpanel/bookings.html", {"page": _page(request, qs), "statuses": Booking.Status.choices})


@admin_required
def booking_detail(request, reference):
    b = get_object_or_404(Booking.objects.select_related("property", "vendor", "customer"), reference=reference)
    if request.method == "POST" and request.POST.get("action") == "cancel":
        try:
            booking_services.cancel_booking(b, request.user, request.POST.get("note", "Cancelled by Heza support"), by_vendor=True)
            messages.success(request, _("Booking cancelled with full refund queued."))
        except booking_services.BookingError as exc:
            messages.error(request, str(exc))
        return redirect("adminpanel:booking_detail", reference=reference)
    return render(request, "adminpanel/booking_detail.html", {
        "b": b, "events": b.events.select_related("actor"), "payments": b.payments.all(), "refunds": b.refunds.all(),
        "ledger": b.ledger_entries.select_related("wallet__vendor"),
    })


@admin_required
def payments(request):
    qs = Payment.objects.select_related("booking__property")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("provider"):
        qs = qs.filter(provider=request.GET["provider"])
    if request.GET.get("q"):
        q = request.GET["q"][:60]
        qs = qs.filter(Q(reference__icontains=q) | Q(booking__reference__icontains=q) | Q(provider_transaction_id__icontains=q))
    return render(request, "adminpanel/payments.html", {"page": _page(request, qs), "statuses": Payment.Status.choices})


@admin_required
@require_POST
def payment_verify(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    payment = pay.verify_payment(payment)
    audit("payment.manual_verify", request=request, target=payment, status=payment.status)
    messages.info(request, _("Provider says: %(s)s") % {"s": payment.get_status_display()})
    return redirect("adminpanel:payments")


@admin_required
def webhooks(request):
    qs = WebhookEvent.objects.select_related("payment")
    if request.GET.get("invalid"):
        qs = qs.filter(signature_valid=False)
    return render(request, "adminpanel/webhooks.html", {"page": _page(request, qs, 50)})


@admin_required
def refunds(request):
    qs = Refund.objects.select_related("booking__property", "payment")
    status = request.GET.get("status", "pending")
    if status != "all":
        qs = qs.filter(status=status)
    return render(request, "adminpanel/refunds.html", {"page": _page(request, qs), "status": status, "statuses": Refund.Status.choices})


@admin_required
@require_POST
def refund_action(request, pk, action):
    refund = get_object_or_404(Refund, pk=pk)
    try:
        if action == "process":
            refund = pay.process_refund(refund, request.user)
            if refund.status == Refund.Status.SUCCEEDED:
                messages.success(request, _("Refund sent."))
            elif refund.status == Refund.Status.PROCESSING:
                messages.info(request, _("Provider accepted the refund; it is processing."))
            else:
                messages.error(request, _("Refund failed: %(r)s") % {"r": refund.failure_reason})
        elif action == "reject":
            pay.reject_refund(refund, request.user, request.POST.get("note", "") or "Rejected")
            messages.success(request, _("Refund rejected."))
        elif action == "settled":
            pay.mark_refund_settled(refund, request.user)
            messages.success(request, _("Refund marked as settled."))
    except pay.PaymentError as exc:
        messages.error(request, str(exc))
    return redirect("adminpanel:refunds")


@admin_required
def payouts(request):
    qs = Payout.objects.select_related("vendor")
    status = request.GET.get("status", "open")
    if status == "open":
        qs = qs.filter(status__in=[Payout.Status.REQUESTED, Payout.Status.APPROVED])
    elif status != "all":
        qs = qs.filter(status=status)
    return render(request, "adminpanel/payouts.html", {"page": _page(request, qs), "status": status})


@admin_required
@require_POST
def payout_action(request, pk, action):
    payout = get_object_or_404(Payout, pk=pk)
    note = request.POST.get("note", "")
    try:
        if action == "approve":
            pay.review_payout(payout, request.user, True, note)
        elif action == "reject":
            pay.review_payout(payout, request.user, False, note or "Rejected")
        elif action == "paid":
            ref = request.POST.get("reference", "").strip()
            if not ref:
                raise pay.PaymentError(_("Enter the bank/MoMo transfer reference."))
            pay.mark_payout_paid(payout, request.user, ref)
        messages.success(request, _("Payout updated."))
    except pay.PaymentError as exc:
        messages.error(request, str(exc))
    return redirect("adminpanel:payouts")


# --- Moderation & catalogue ----------------------------------------------------

@admin_required
def reviews(request):
    status = request.GET.get("status", "pending")
    qs = Review.objects.select_related("property", "author", "booking")
    if status != "all":
        qs = qs.filter(status=status)
    return render(request, "adminpanel/reviews.html", {"page": _page(request, qs), "status": status})


@admin_required
@require_POST
def review_action(request, pk, action):
    review = get_object_or_404(Review, pk=pk)
    if action in ("approve", "reject"):
        review.status = Review.Status.APPROVED if action == "approve" else Review.Status.REJECTED
        review.moderation_note = request.POST.get("note", "")[:255]
        review.moderated_by = request.user
        review.save()
        refresh_property_rating(review.property)
        audit(f"review.{action}", request=request, target=review)
        messages.success(request, _("Review %(s)s.") % {"s": review.get_status_display().lower()})
    return redirect(reverse("adminpanel:reviews") + f"?status={request.POST.get('return_status', 'pending')}")


@admin_required
def coupons(request):
    form = CouponForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        c = form.save()
        audit("coupon.created", request=request, target=c)
        messages.success(request, _("Platform promo code created."))
        return redirect("adminpanel:coupons")
    return render(request, "adminpanel/coupons.html", {"form": form, "coupons": Coupon.objects.select_related("vendor")})


@admin_required
@require_POST
def coupon_toggle(request, pk):
    c = get_object_or_404(Coupon, pk=pk)
    c.is_active = not c.is_active
    c.save(update_fields=["is_active", "updated_at"])
    return redirect("adminpanel:coupons")


class AmenityForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Amenity
        fields = ["name", "icon", "scope"]


@admin_required
def amenities(request):
    form = AmenityForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Amenity added."))
        return redirect("adminpanel:amenities")
    return render(request, "adminpanel/amenities.html", {"form": form, "amenities": Amenity.objects.annotate(n=Count("properties"))})


@admin_required
@require_POST
def amenity_delete(request, pk):
    get_object_or_404(Amenity, pk=pk).delete()
    messages.success(request, _("Amenity removed."))
    return redirect("adminpanel:amenities")


# --- Reports, settings, audit --------------------------------------------------

@admin_required
def reports_view(request):
    start, end = reports.parse_range(request)
    vendor = None
    if request.GET.get("vendor", "").isdigit():
        vendor = Vendor.objects.filter(pk=request.GET["vendor"]).first()
    scope = reports.Scope(vendor)
    kind = request.GET.get("download")
    if kind in reports.REPORT_KINDS:
        return reports.csv_response(kind, scope, start, end)
    return render(request, "adminpanel/reports.html", {
        "s": reports.summary(scope, start, end), "occupancy": reports.occupancy(scope, start, end), "kinds": reports.REPORT_KINDS,
        "start": start, "end": end, "vendors": Vendor.objects.filter(status="approved"), "vendor": vendor,
    })


class PlatformSettingsForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = PlatformSettings
        fields = ["commission_rate", "tax_rate", "tax_inclusive", "min_payout_amount", "support_phone", "support_email"]


class CategoryCommissionForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CategoryCommission
        fields = ["category", "rate"]
        widgets = {"category": forms.Select(choices=Category.choices)}

    def validate_unique(self):
        """Saving an existing category updates its rate (see update_or_create in the view)."""


@admin_required
def settings_view(request):
    obj = PlatformSettings.load()
    obj = PlatformSettings.objects.get(pk=obj.pk)
    form = PlatformSettingsForm(request.POST if request.POST.get("section") == "platform" else None, instance=obj)
    cat_form = CategoryCommissionForm(request.POST if request.POST.get("section") == "category" else None)
    if request.method == "POST":
        if request.POST.get("section") == "platform" and form.is_valid():
            form.save()
            audit("settings.updated", request=request, target=obj, commission=str(obj.commission_rate), tax=str(obj.tax_rate))
            messages.success(request, _("Platform settings saved."))
            return redirect("adminpanel:settings")
        if request.POST.get("section") == "category" and cat_form.is_valid():
            CategoryCommission.objects.update_or_create(category=cat_form.cleaned_data["category"], defaults={"rate": cat_form.cleaned_data["rate"]})
            audit("settings.category_commission", request=request, category=cat_form.cleaned_data["category"], rate=str(cat_form.cleaned_data["rate"]))
            messages.success(request, _("Category commission saved."))
            return redirect("adminpanel:settings")
        if request.POST.get("section") == "category_delete":
            CategoryCommission.objects.filter(pk=request.POST.get("pk")).delete()
            return redirect("adminpanel:settings")
    return render(request, "adminpanel/settings.html", {"form": form, "cat_form": cat_form, "categories": CategoryCommission.objects.all(),
                                                         "category_labels": dict(Category.choices)})


@admin_required
def audit_log(request):
    qs = AuditLog.objects.select_related("actor")
    if request.GET.get("action"):
        qs = qs.filter(action__startswith=request.GET["action"][:40])
    if request.GET.get("q"):
        q = request.GET["q"][:60]
        qs = qs.filter(Q(description__icontains=q) | Q(actor__email__icontains=q) | Q(target_id=q))
    return render(request, "adminpanel/audit.html", {"page": _page(request, qs, 50)})


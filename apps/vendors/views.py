import mimetypes

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.forms import LoginForm
from apps.accounts.models import Role
from apps.accounts.views import _dev_link
from apps.core.audit import audit
from apps.core.ratelimit import ratelimit
from apps.notifications.services import notify_admins, send_verification_email

from .forms import (
    AcceptInviteForm,
    DocumentForm,
    PartnerRegisterForm,
    PayoutDetailsForm,
    VendorProfileForm,
)
from .models import StaffInvite, StaffMembership, Vendor, VendorDocument

REQUIRED_DOCS = [VendorDocument.DocType.RDB_CERTIFICATE, VendorDocument.DocType.OWNER_ID]


@ratelimit("partner_register", "8/h")
def partner_register(request):
    if request.user.is_authenticated and request.user.is_vendor_user:
        return redirect("dashboard:overview")
    form = PartnerRegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save(role=Role.VENDOR_OWNER)
            vendor = Vendor.objects.create(owner=user, business_name=form.cleaned_data["business_name"], email=user.email, phone=user.phone)
        login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
        _dev_link(request, send_verification_email(user, request))
        audit("vendor.registered", actor=user, target=vendor, request=request)
        messages.success(request, _("Account created. Complete your business profile to get verified."))
        return redirect("vendors:onboarding")
    return render(request, "vendors/register.html", {"form": form})


@method_decorator(ratelimit("login", "10/m"), name="dispatch")
class PartnerLoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = "vendors/login.html"
    redirect_authenticated_user = True


def _owner_vendor(request):
    if not request.user.is_authenticated:
        return None
    if request.user.role != Role.VENDOR_OWNER:
        raise PermissionDenied
    vendor = request.user.owned_vendors.order_by("created_at").first()
    if vendor is None:
        vendor = Vendor.objects.create(owner=request.user, business_name=request.user.display_name, email=request.user.email,
                                       phone=request.user.phone or "")
    return vendor


def onboarding_state(vendor):
    uploaded = set(vendor.documents.exclude(status=VendorDocument.Status.REJECTED).values_list("doc_type", flat=True))
    steps = [
        {"key": "profile", "label": _("Business details"), "done": bool(vendor.legal_name and vendor.tin and vendor.address)},
        {"key": "payout", "label": _("Payout details"), "done": bool(vendor.payout_momo_number or vendor.payout_account_number)},
        {"key": "documents", "label": _("Verification documents"), "done": all(d in uploaded for d in REQUIRED_DOCS)},
        {"key": "property", "label": _("First property draft"), "done": vendor.properties.exists()},
    ]
    return steps, all(s["done"] for s in steps[:3])


@login_required(login_url="vendors:login")
def onboarding(request):
    vendor = _owner_vendor(request)
    profile_form = VendorProfileForm(instance=vendor, prefix="p")
    payout_form = PayoutDetailsForm(instance=vendor, prefix="pay")
    doc_form = DocumentForm(prefix="d")
    if request.method == "POST":
        section = request.POST.get("section")
        if vendor.status in (Vendor.Status.PENDING, Vendor.Status.SUSPENDED) and section in ("profile", "payout"):
            messages.warning(request, _("Your application is under review; contact support to change details."))
            return redirect("vendors:onboarding")
        if section == "profile":
            profile_form = VendorProfileForm(request.POST, request.FILES, instance=vendor, prefix="p")
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, _("Business details saved."))
                return redirect("vendors:onboarding")
        elif section == "payout":
            payout_form = PayoutDetailsForm(request.POST, instance=vendor, prefix="pay")
            if payout_form.is_valid():
                payout_form.save()
                audit("vendor.payout_details_changed", request=request, target=vendor)
                messages.success(request, _("Payout details saved."))
                return redirect("vendors:onboarding")
        elif section == "documents":
            doc_form = DocumentForm(request.POST, request.FILES, prefix="d")
            if doc_form.is_valid():
                doc = doc_form.save(commit=False)
                doc.vendor = vendor
                doc.original_name = request.FILES["d-file"].name[:200]
                doc.save()
                audit("vendor.document_uploaded", request=request, target=vendor, doc_type=doc.doc_type)
                messages.success(request, _("Document uploaded."))
                return redirect("vendors:onboarding")
    steps, ready = onboarding_state(vendor)
    return render(request, "vendors/onboarding.html", {
        "vendor": vendor, "profile_form": profile_form, "payout_form": payout_form, "doc_form": doc_form,
        "steps": steps, "ready": ready, "documents": vendor.documents.all(), "required_docs": REQUIRED_DOCS,
    })


@login_required(login_url="vendors:login")
@require_POST
def submit_application(request):
    vendor = _owner_vendor(request)
    steps, ready = onboarding_state(vendor)
    if not request.user.is_email_verified:
        messages.error(request, _("Confirm your email address before submitting."))
    elif not ready:
        messages.error(request, _("Complete business details, payout details and required documents first."))
    elif vendor.status not in (Vendor.Status.DRAFT, Vendor.Status.REJECTED):
        messages.info(request, _("Your application has already been submitted."))
    else:
        vendor.status = Vendor.Status.PENDING
        vendor.submitted_at = timezone.now()
        vendor.save(update_fields=["status", "submitted_at", "updated_at"])
        audit("vendor.submitted", request=request, target=vendor)
        from django.urls import reverse

        notify_admins("vendor_submitted", _("New vendor application: %(v)s") % {"v": vendor}, reverse("adminpanel:vendor_detail", args=[vendor.pk]))
        messages.success(request, _("Application submitted. We usually review within one business day."))
    return redirect("vendors:onboarding")


@login_required(login_url="vendors:login")
@require_POST
def document_delete(request, pk):
    vendor = _owner_vendor(request)
    doc = get_object_or_404(VendorDocument, pk=pk, vendor=vendor)
    if doc.status == VendorDocument.Status.ACCEPTED:
        messages.error(request, _("Accepted documents can't be removed."))
    else:
        doc.file.delete(save=False)
        doc.delete()
        messages.success(request, _("Document removed."))
    return redirect("vendors:onboarding")


@login_required
def document_download(request, pk):
    doc = get_object_or_404(VendorDocument.objects.select_related("vendor"), pk=pk)
    user = request.user
    allowed = user.is_platform_admin or doc.vendor.owner_id == user.pk
    if not allowed:
        raise Http404
    try:
        fh = doc.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    ctype = mimetypes.guess_type(doc.file.name)[0] or "application/octet-stream"
    audit("vendor.document_viewed", request=request, target=doc)
    resp = FileResponse(fh, content_type=ctype, as_attachment=False, filename=doc.original_name or doc.file.name.rsplit("/", 1)[-1])
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; plugin-types application/pdf"
    return resp


def accept_invite(request, token):
    invite = get_object_or_404(StaffInvite.objects.select_related("vendor"), token=token)
    if not invite.is_usable:
        return render(request, "vendors/invite_invalid.html", {"invite": invite}, status=410)
    from apps.accounts.models import User

    existing = User.objects.filter(email__iexact=invite.email).first()
    form = None
    if request.user.is_authenticated:
        if request.user.email.lower() != invite.email.lower():
            messages.error(request, _("This invitation was sent to %(e)s. Sign out and open the link again.") % {"e": invite.email})
            return render(request, "vendors/invite_accept.html", {"invite": invite, "mismatch": True})
        if request.method == "POST":
            _accept(invite, request.user, request)
            return redirect("dashboard:overview")
    elif existing:
        messages.info(request, _("Sign in as %(e)s to accept this invitation.") % {"e": invite.email})
        from django.urls import reverse

        return redirect(f"{reverse('vendors:login')}?next={request.path}")
    else:
        form = AcceptInviteForm(request.POST or None, invite=invite)
        if request.method == "POST" and form.is_valid():
            user = form.save(role=invite.role)
            user.is_email_verified = True  # the invite link proves control of the address
            user.save(update_fields=["is_email_verified"])
            login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
            _accept(invite, user, request)
            return redirect("dashboard:overview")
    return render(request, "vendors/invite_accept.html", {"invite": invite, "form": form})


def _accept(invite, user, request):
    if user.role in (Role.SUPER_ADMIN, Role.VENDOR_OWNER):
        messages.error(request, _("This account type can't join another business as staff."))
        return
    with transaction.atomic():
        membership, _created = StaffMembership.objects.update_or_create(
            vendor=invite.vendor, user=user, defaults={"role": invite.role, "is_active": True}
        )
        membership.properties.set(invite.properties.all())
        user.memberships.exclude(pk=membership.pk).update(is_active=False)
        user.role = invite.role
        user.save(update_fields=["role"])
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])
    audit("staff.invite_accepted", actor=user, target=invite.vendor, request=request, role=invite.role)
    messages.success(request, _("You've joined %(v)s.") % {"v": invite.vendor})


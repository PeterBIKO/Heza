"""Role-based access control.

Platform roles live on User.role. Vendor staff are additionally scoped by StaffMembership to one
vendor and (optionally) a subset of its properties. Every dashboard query goes through
VendorContext so a receptionist at one property can never read another vendor's data.
"""
import functools
from dataclasses import dataclass, field

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from apps.accounts.models import Role

PERMISSIONS = {
    Role.VENDOR_OWNER: {
        "listings", "pricing", "availability", "bookings", "offline_payments", "reports",
        "reviews", "inquiries", "finance", "staff", "settings", "coupons",
    },
    Role.PROPERTY_MANAGER: {
        "listings", "pricing", "availability", "bookings", "offline_payments", "reports", "reviews", "inquiries", "coupons",
    },
    Role.RECEPTIONIST: {"bookings", "offline_payments", "availability_view", "inquiries"},
}
PERMISSIONS[Role.PROPERTY_MANAGER].add("availability_view")
PERMISSIONS[Role.VENDOR_OWNER].add("availability_view")


@dataclass
class VendorContext:
    vendor: object
    role: str
    membership: object = None
    _property_ids: set = field(default=None)

    def can(self, perm):
        return perm in PERMISSIONS.get(self.role, set())

    @property
    def is_owner(self):
        return self.role == Role.VENDOR_OWNER

    @property
    def scoped(self):
        """True when the user is limited to specific properties."""
        return self.membership is not None and self.membership.properties.exists()

    def properties(self):
        qs = self.vendor.properties.all()
        if self.scoped:
            qs = qs.filter(pk__in=self.membership.properties.values("pk"))
        return qs

    def property_ids(self):
        if self._property_ids is None:
            self._property_ids = set(self.properties().values_list("pk", flat=True))
        return self._property_ids

    def get_property(self, pk):
        prop = self.properties().filter(pk=pk).first()
        if prop is None:
            raise Http404
        return prop

    def bookings(self):
        from apps.bookings.models import Booking

        return Booking.objects.filter(vendor=self.vendor, property_id__in=self.property_ids())


def get_vendor_context(user):
    if not user.is_authenticated or user.is_suspended:
        return None
    if user.role == Role.VENDOR_OWNER:
        vendor = user.owned_vendors.order_by("created_at").first()
        return VendorContext(vendor=vendor, role=Role.VENDOR_OWNER) if vendor else None
    if user.role in (Role.PROPERTY_MANAGER, Role.RECEPTIONIST):
        membership = user.memberships.select_related("vendor").filter(is_active=True).first()
        if membership:
            return VendorContext(vendor=membership.vendor, role=membership.role, membership=membership)
    return None


def vendor_required(perm=None, approved=False):
    """Decorator for vendor dashboard views. Sets request.vctx."""

    def decorator(view):
        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), "vendors:login")
            if request.user.role == Role.VENDOR_OWNER and not request.user.owned_vendors.exists():
                return redirect("vendors:onboarding")
            ctx = get_vendor_context(request.user)
            if ctx is None:
                raise PermissionDenied(_("You do not have access to a vendor dashboard."))
            if ctx.vendor.status == "suspended":
                messages.error(request, _("This business is suspended. Contact Heza support."))
                raise PermissionDenied
            if perm and not ctx.can(perm):
                raise PermissionDenied(_("Your role does not allow this action."))
            if approved and not ctx.vendor.is_approved:
                messages.warning(request, _("This action is available once Heza approves your business."))
                return redirect("dashboard:overview")
            request.vctx = ctx
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def admin_required(view):
    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), "accounts:login")
        if not request.user.is_platform_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


def customer_required(view):
    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), "accounts:login")
        return view(request, *args, **kwargs)

    return wrapped

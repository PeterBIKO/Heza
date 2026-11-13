from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role
from apps.bookings import services as bs
from apps.core.models import AuditLog
from apps.core.testing import (
    add_staff,
    days,
    make_property,
    make_room,
    make_user,
    make_vendor,
)
from apps.payments.models import SandboxTransaction
from apps.properties.models import Property
from apps.reports.services import _safe_cell

from .rbac import PERMISSIONS
from .templatetags.heza import money


def booking_for(room, customer=None):
    customer = customer or make_user()
    return bs.create_room_booking(customer=customer, room_type_id=room.pk, check_in=days(10), check_out=days(12), rooms=1,
                                  adults=1, children=0, guest=bs.GuestDetails("Guest", customer.email, "+250788000000", ""))


@override_settings(RATELIMIT_ENABLED=False)
class VendorIsolationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.vendor_a = make_vendor()
        self.vendor_b = make_vendor()
        self.prop_a = make_property(self.vendor_a)
        self.prop_a2 = make_property(self.vendor_a)
        self.prop_b = make_property(self.vendor_b)
        self.room_b = make_room(self.prop_b)
        self.booking_b = booking_for(self.room_b)

    def test_owner_cannot_see_other_vendor_data(self):
        self.client.force_login(self.vendor_a.owner)
        self.assertEqual(self.client.get(reverse("dashboard:booking_detail", args=[self.booking_b.reference])).status_code, 404)
        self.assertEqual(self.client.get(reverse("dashboard:property_edit", args=[self.prop_b.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("dashboard:room_edit", args=[self.room_b.pk])).status_code, 404)
        r = self.client.post(reverse("dashboard:booking_action", args=[self.booking_b.reference, "cancel"]), {"reason": "x"})
        self.assertEqual(r.status_code, 404)
        listing = self.client.get(reverse("dashboard:bookings"))
        self.assertNotContains(listing, self.booking_b.reference)

    def test_receptionist_permissions(self):
        rec = add_staff(self.vendor_a, Role.RECEPTIONIST)
        self.client.force_login(rec)
        self.assertEqual(self.client.get(reverse("dashboard:bookings")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:calendar")).status_code, 200)
        for name in ("dashboard:wallet", "dashboard:staff", "dashboard:properties", "dashboard:reports", "dashboard:settings", "dashboard:coupons"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_manager_scoped_to_assigned_properties(self):
        mgr = add_staff(self.vendor_a, Role.PROPERTY_MANAGER, properties=[self.prop_a])
        self.client.force_login(mgr)
        self.assertEqual(self.client.get(reverse("dashboard:property_edit", args=[self.prop_a.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:property_edit", args=[self.prop_a2.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("dashboard:wallet")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard:property_create")).status_code, 302)

    def test_customer_and_anonymous_blocked_from_dashboards(self):
        self.assertEqual(self.client.get(reverse("dashboard:overview")).status_code, 302)
        self.assertEqual(self.client.get(reverse("adminpanel:overview")).status_code, 302)
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("dashboard:overview")).status_code, 403)
        self.assertEqual(self.client.get(reverse("adminpanel:overview")).status_code, 403)

    def test_vendor_cannot_reach_admin_panel(self):
        self.client.force_login(self.vendor_a.owner)
        self.assertEqual(self.client.get(reverse("adminpanel:vendors")).status_code, 403)
        self.assertEqual(self.client.post(reverse("adminpanel:vendor_action", args=[self.vendor_a.pk, "approve"])).status_code, 403)

    def test_admin_actions_are_audited(self):
        admin = make_user(Role.SUPER_ADMIN, is_staff=True)
        self.client.force_login(admin)
        pending = make_vendor(status="pending")
        self.client.post(reverse("adminpanel:vendor_action", args=[pending.pk, "approve"]))
        pending.refresh_from_db()
        self.assertEqual(pending.status, "approved")
        self.assertTrue(AuditLog.objects.filter(action="vendor.approve", actor=admin).exists())

    def test_customer_cannot_view_others_booking(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("bookings:detail", args=[self.booking_b.reference])).status_code, 404)

    def test_permission_matrix_is_least_privilege(self):
        self.assertNotIn("finance", PERMISSIONS[Role.PROPERTY_MANAGER])
        self.assertNotIn("staff", PERMISSIONS[Role.PROPERTY_MANAGER])
        self.assertEqual(PERMISSIONS[Role.RECEPTIONIST], {"bookings", "offline_payments", "availability_view", "inquiries"})


class PublicVisibilityTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_only_verified_property_of_approved_vendor_is_public(self):
        live = make_property(name="Live Lodge")
        draft = make_property(name="Draft Lodge", status="draft")
        unapproved = make_property(vendor=make_vendor(status="pending"), name="Unapproved Lodge")
        public = set(Property.objects.public().values_list("pk", flat=True))
        self.assertEqual(public, {live.pk})
        r = self.client.get(reverse("public:search"))
        self.assertContains(r, "Live Lodge")
        self.assertNotContains(r, "Draft Lodge")
        self.assertNotContains(r, "Unapproved Lodge")
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(unapproved.get_absolute_url()).status_code, 404)

    def test_owner_can_preview_draft(self):
        draft = make_property(status="draft")
        self.client.force_login(draft.vendor.owner)
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 200)


class SecurityTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_security_headers(self):
        r = self.client.get("/")
        self.assertIn("default-src 'self'", r["Content-Security-Policy"])
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_user_content_is_escaped(self):
        make_property(name="<script>alert(1)</script> Inn")
        r = self.client.get(reverse("public:search"))
        self.assertNotContains(r, "<script>alert(1)</script>")
        self.assertContains(r, "&lt;script&gt;")

    def test_csv_formula_injection_neutralised(self):
        self.assertEqual(_safe_cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(_safe_cell("Kigali"), "Kigali")

    def test_money_filter(self):
        self.assertEqual(money(Decimal("1234567.4")), "RWF 1,234,567")

    def test_csrf_enforced_on_forms(self):
        from django.test import Client

        c = Client(enforce_csrf_checks=True)
        r = c.post(reverse("accounts:login"), {"username": "a@b.rw", "password": "x"})
        self.assertEqual(r.status_code, 403)

    def test_webhook_rejects_oversized_payload(self):
        r = self.client.post(reverse("payments:webhook", args=["sandbox"]), data=b"x" * 70000, content_type="application/json")
        self.assertEqual(r.status_code, 413)

    def test_login_rate_limited(self):
        for _ in range(10):
            self.client.post(reverse("accounts:login"), {"username": "nobody@test.rw", "password": "wrong"})
        r = self.client.post(reverse("accounts:login"), {"username": "nobody@test.rw", "password": "wrong"})
        self.assertEqual(r.status_code, 429)


@override_settings(RATELIMIT_ENABLED=False, PAYMENT_PROVIDERS_ENABLED=["sandbox"])
class EndToEndBookingTests(TestCase):
    """Guest books through the real forms, pays on the sandbox gateway, vendor sees it confirmed."""

    def setUp(self):
        cache.clear()
        self.room = make_room(quantity=1, price=80000)
        self.guest = make_user()

    def test_book_pay_confirm(self):
        self.client.force_login(self.guest)
        url = reverse("bookings:book_room", args=[self.room.pk])
        r = self.client.post(url, {"check_in": days(14).isoformat(), "check_out": days(16).isoformat(), "rooms": 1, "adults": 2, "children": 0,
                                   "guest_name": "Grace U", "guest_email": self.guest.email, "guest_phone": "0788123456"})
        self.assertEqual(r.status_code, 302, r.content[:500])
        booking = self.guest.bookings.get()
        self.assertEqual(booking.status, "pending")
        self.assertEqual(booking.total, Decimal("188800"))

        r = self.client.post(reverse("bookings:pay", args=[booking.reference]), {"option": "full", "provider": "sandbox"})
        self.assertEqual(r.status_code, 302)
        txn = SandboxTransaction.objects.get()
        self.assertIn(txn.txn_id, r["Location"])
        self.client.post(reverse("payments:sandbox_checkout", args=[txn.txn_id]), {"action": "approve", "method": "mobilemoneyrw"})
        booking.refresh_from_db()
        self.assertEqual(booking.status, "confirmed")
        self.assertEqual(booking.payment_status, "paid")

        other = make_user()
        self.client.force_login(other)
        r = self.client.post(url, {"check_in": days(15).isoformat(), "check_out": days(17).isoformat(), "rooms": 1, "adults": 1, "children": 0,
                                   "guest_name": "Other", "guest_email": other.email, "guest_phone": "0788000999"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(other.bookings.count(), 0)

        self.client.force_login(self.room.property.vendor.owner)
        r = self.client.get(reverse("dashboard:booking_detail", args=[booking.reference]))
        self.assertContains(r, booking.reference)
        self.assertContains(r, "Confirmed")

    def test_unverified_email_cannot_book(self):
        user = make_user(is_email_verified=False)
        self.client.force_login(user)
        r = self.client.get(reverse("bookings:book_room", args=[self.room.pk]))
        self.assertRedirects(r, reverse("accounts:verify_sent"), fetch_redirect_response=False)

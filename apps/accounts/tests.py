from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.testing import PASSWORD, make_user

from .models import Role, User
from .tokens import make_email_token


@override_settings(RATELIMIT_ENABLED=False)
class AccountFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_register_sends_verification_and_verify_link_works(self):
        r = self.client.post(reverse("accounts:register"), {
            "first_name": "Aline", "last_name": "Keza", "email": "aline@test.rw", "phone": "0788555667",
            "password1": "Strong-pass-9876", "password2": "Strong-pass-9876", "accept_terms": "on",
        })
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(email="aline@test.rw")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertEqual(user.phone, "+250788555667")
        self.assertFalse(user.is_email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.client.get(reverse("accounts:verify_email", args=[make_email_token(user)]))
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)

    def test_tampered_token_rejected(self):
        user = make_user(is_email_verified=False)
        self.client.get(reverse("accounts:verify_email", args=[make_email_token(user) + "x"]))
        user.refresh_from_db()
        self.assertFalse(user.is_email_verified)

    def test_login_with_email_or_phone(self):
        user = make_user()
        self.assertTrue(self.client.login(username=user.email, password=PASSWORD))
        self.client.logout()
        self.assertTrue(self.client.login(username=user.phone, password=PASSWORD))

    def test_suspended_user_cannot_log_in_and_is_logged_out(self):
        user = make_user()
        self.client.force_login(user)
        user.suspend("fraud review")
        r = self.client.get(reverse("bookings:mine"))
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        r = self.client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_reset_email(self):
        user = make_user()
        self.client.post(reverse("accounts:password_reset"), {"email": user.email})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/", mail.outbox[0].body)

    def test_partner_registration_creates_owner_and_vendor(self):
        r = self.client.post(reverse("vendors:register"), {
            "business_name": "Hilltop Lodge", "first_name": "Eric", "last_name": "H", "email": "eric@test.rw", "phone": "0788111001",
            "password1": "Strong-pass-9876", "password2": "Strong-pass-9876", "accept_terms": "on",
        })
        self.assertEqual(r.status_code, 302, r.content[:400])
        user = User.objects.get(email="eric@test.rw")
        self.assertEqual(user.role, Role.VENDOR_OWNER)
        self.assertEqual(user.owned_vendors.get().status, "draft")

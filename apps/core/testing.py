"""Small object factories shared by the test suites."""
import itertools
from datetime import time, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import Role, User
from apps.properties.models import Property, RoomType, Venue
from apps.vendors.models import StaffMembership, Vendor

PASSWORD = "Test-pass-123!"
_seq = itertools.count(1)


def make_user(role=Role.CUSTOMER, email=None, **extra):
    n = next(_seq)
    extra.setdefault("is_email_verified", True)
    return User.objects.create_user(email=email or f"user{n}@test.rw", password=PASSWORD, role=role,
                                    first_name="Test", last_name=f"User{n}", phone=f"+25078800{n:04d}", **extra)


def make_vendor(owner=None, status=Vendor.Status.APPROVED, **extra):
    owner = owner or make_user(Role.VENDOR_OWNER)
    n = next(_seq)
    return Vendor.objects.create(owner=owner, business_name=f"Vendor {n}", email=f"vendor{n}@test.rw", phone="+250788000111",
                                 status=status, payout_momo_number="+250788000111", **extra)


def make_property(vendor=None, status=Property.Status.VERIFIED, **extra):
    vendor = vendor or make_vendor()
    n = next(_seq)
    defaults = {"name": f"Property {n}", "category": "hotel", "description": "Test property", "address": "KG 1 Ave", "city": "Kigali",
                "latitude": Decimal("-1.95"), "longitude": Decimal("30.06"), "cancellation_policy": "moderate"}
    defaults.update(extra)
    return Property.objects.create(vendor=vendor, status=status, **defaults)


def make_room(prop=None, quantity=2, price=100000, **extra):
    prop = prop or make_property()
    return RoomType.objects.create(property=prop, name=extra.pop("name", "Deluxe"), base_price=Decimal(price), quantity=quantity,
                                   max_adults=extra.pop("max_adults", 2), max_children=extra.pop("max_children", 1), **extra)


def make_venue(prop=None, **extra):
    prop = prop or make_property(category="hall")
    defaults = {"name": "Grand Hall", "capacity_seated": 200, "capacity_standing": 300, "hourly_price": Decimal("50000"),
                "half_day_price": Decimal("200000"), "full_day_price": Decimal("350000"), "event_price": Decimal("500000"),
                "min_hours": 2, "opening_time": time(8, 0), "closing_time": time(23, 0), "turnover_minutes": 60}
    defaults.update(extra)
    return Venue.objects.create(property=prop, **defaults)


def add_staff(vendor, role=Role.RECEPTIONIST, properties=()):
    user = make_user(role)
    m = StaffMembership.objects.create(vendor=vendor, user=user, role=role)
    if properties:
        m.properties.set(properties)
    return user


def days(n):
    return timezone.localdate() + timedelta(days=n)

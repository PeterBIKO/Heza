import threading
from datetime import time, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.core.models import CategoryCommission
from apps.core.testing import (
    days,
    make_property,
    make_room,
    make_user,
    make_vendor,
    make_venue,
)
from apps.properties.models import Property, RoomBlock, SeasonalRate, VenueBlock

from . import services
from .availability import (
    room_availability,
    search_available_property_ids,
    units_available,
    venue_is_free,
)
from .models import Booking, Coupon
from .pricing import nightly_rate, quote_room


def guest(user):
    return services.GuestDetails("Test Guest", user.email, "+250788123456", "")


def book_room(customer, room, check_in, check_out, rooms=1, **kw):
    return services.create_room_booking(customer=customer, room_type_id=room.pk, check_in=check_in, check_out=check_out,
                                        rooms=rooms, adults=1, children=0, guest=guest(customer), **kw)


class RoomAvailabilityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = make_user()
        self.room = make_room(quantity=2)

    def test_free_units_drop_with_bookings_and_blocks(self):
        book_room(self.customer, self.room, days(5), days(8))
        RoomBlock.objects.create(room_type=self.room, start_date=days(6), end_date=days(7), units=1)
        avail = room_availability(self.room, days(4), days(9))
        self.assertEqual([avail[days(i)] for i in range(4, 9)], [2, 1, 0, 1, 2])

    def test_checkout_day_is_bookable_again(self):
        book_room(self.customer, self.room, days(5), days(7), rooms=2)
        self.assertEqual(units_available(self.room, days(7), days(9)), 2)
        self.assertEqual(units_available(self.room, days(6), days(8)), 0)

    def test_cannot_overbook_last_unit(self):
        book_room(self.customer, self.room, days(10), days(12), rooms=2)
        with self.assertRaises(services.BookingError):
            book_room(make_user(), self.room, days(11), days(13))

    def test_expired_hold_releases_inventory(self):
        b = book_room(self.customer, self.room, days(10), days(12), rooms=2)
        Booking.objects.filter(pk=b.pk).update(hold_expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(units_available(self.room, days(10), days(12)), 2)
        self.assertEqual(services.expire_stale_holds(), 1)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.EXPIRED)
        book_room(make_user(), self.room, days(10), days(12), rooms=2)

    def test_pay_later_request_holds_inventory_without_expiry(self):
        prop = self.room.property
        prop.allow_pay_later = True
        prop.save()
        b = book_room(self.customer, self.room, days(10), days(12), rooms=2, pay_later=True)
        Booking.objects.filter(pk=b.pk).update(hold_expires_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(units_available(self.room, days(10), days(12)), 0)
        self.assertEqual(services.expire_stale_holds(), 0)

    def test_cancelled_booking_frees_dates(self):
        b = book_room(self.customer, self.room, days(10), days(12), rooms=2)
        services.cancel_booking(b, self.customer, "changed plans")
        self.assertEqual(units_available(self.room, days(10), days(12)), 2)

    def test_validation_rules(self):
        with self.assertRaises(services.BookingError):
            book_room(self.customer, self.room, days(-1), days(1))
        with self.assertRaises(services.BookingError):
            book_room(self.customer, self.room, days(3), days(3))
        with self.assertRaises(services.BookingError):
            services.create_room_booking(customer=self.customer, room_type_id=self.room.pk, check_in=days(3), check_out=days(4),
                                         rooms=1, adults=3, children=0, guest=guest(self.customer))

    def test_unverified_property_cannot_be_booked(self):
        draft = make_room(prop=make_property(status="draft"))
        with self.assertRaises(services.BookingError):
            book_room(self.customer, draft, days(3), days(4))

    def test_search_filters_out_sold_out_properties(self):
        other = make_room(quantity=1)
        book_room(self.customer, other, days(3), days(5))
        ids = search_available_property_ids(Property.objects.public(), days(3), days(5), guests=1)
        self.assertIn(self.room.property_id, ids)
        self.assertNotIn(other.property_id, ids)


class VenueAvailabilityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = make_user()
        self.venue = make_venue()

    def book(self, day, mode, start_time=None, hours=None, customer=None):
        customer = customer or self.customer
        return services.create_venue_booking(customer=customer, venue_id=self.venue.pk, day=day, mode=mode, start_time=start_time,
                                             hours=hours, guests=50, guest=guest(customer))

    def test_full_day_blocks_overlapping_hourly(self):
        self.book(days(20), "full_day")
        with self.assertRaises(services.BookingError):
            self.book(days(20), "hourly", time(14, 0), 2, customer=make_user())

    def test_turnover_buffer_is_enforced(self):
        self.book(days(20), "hourly", time(10, 0), 2)
        with self.assertRaises(services.BookingError):
            self.book(days(20), "hourly", time(12, 30), 2, customer=make_user())
        self.book(days(20), "hourly", time(13, 0), 2, customer=make_user())

    def test_am_and_pm_half_days_do_not_conflict(self):
        self.book(days(21), "half_day_am")
        self.book(days(21), "half_day_pm", customer=make_user())
        self.assertEqual(Booking.objects.filter(venue=self.venue).count(), 2)

    def test_blocks_and_opening_hours(self):
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(timezone.datetime.combine(days(22), time(9, 0)), tz)
        VenueBlock.objects.create(venue=self.venue, start_at=start, end_at=start + timedelta(hours=3))
        self.assertFalse(venue_is_free(self.venue, start + timedelta(hours=1), start + timedelta(hours=2)))
        with self.assertRaises(services.BookingError):
            self.book(days(23), "hourly", time(22, 0), 3)

    def test_capacity_limit(self):
        with self.assertRaises(services.BookingError):
            services.create_venue_booking(customer=self.customer, venue_id=self.venue.pk, day=days(20), mode="full_day",
                                          guests=self.venue.max_capacity + 1, guest=guest(self.customer))


class PricingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.room = make_room(price=100000, weekend_price=Decimal("120000"))

    def first_weekday(self, weekday, after=5):
        d = days(after)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        return d

    def test_rate_precedence(self):
        friday = self.first_weekday(4)
        monday = self.first_weekday(0)
        self.assertEqual(nightly_rate(self.room, monday)[0], Decimal("100000"))
        self.assertEqual(nightly_rate(self.room, friday)[0], Decimal("120000"))
        SeasonalRate.objects.create(room_type=self.room, name="Peak", start_date=friday, end_date=friday, nightly_price=Decimal("150000"))
        self.assertEqual(nightly_rate(self.room, friday)[0], Decimal("150000"))

    def test_tax_exclusive_total_and_deposit(self):
        prop = self.room.property
        prop.payment_mode = "deposit"
        prop.deposit_percent = Decimal("30")
        prop.save()
        monday = self.first_weekday(0)
        q = quote_room(self.room, monday, monday + timedelta(days=2), rooms=1)
        self.assertEqual(q.subtotal, Decimal("200000"))
        self.assertEqual(q.tax, Decimal("36000"))
        self.assertEqual(q.total, Decimal("236000"))
        self.assertEqual(q.deposit, Decimal("70800"))

    def test_coupon_validity_and_scope(self):
        monday = self.first_weekday(0)
        Coupon.objects.create(code="TEN", percent_off=Decimal("10"))
        other_vendor = make_vendor()
        Coupon.objects.create(code="OTHER", percent_off=Decimal("50"), vendor=other_vendor)
        q = quote_room(self.room, monday, monday + timedelta(days=1), coupon_code="ten")
        self.assertEqual(q.discount, Decimal("10000"))
        q2 = quote_room(self.room, monday, monday + timedelta(days=1), coupon_code="OTHER")
        self.assertEqual(q2.discount, 0)
        self.assertTrue(q2.coupon_error)

    def test_commission_precedence(self):
        monday = self.first_weekday(0)
        self.assertEqual(quote_room(self.room, monday, monday + timedelta(days=1)).commission_rate, Decimal("10"))
        CategoryCommission.objects.create(category="hotel", rate=Decimal("12"))
        self.assertEqual(quote_room(self.room, monday, monday + timedelta(days=1)).commission_rate, Decimal("12"))
        vendor = self.room.property.vendor
        vendor.commission_rate = Decimal("8")
        vendor.save()
        self.assertEqual(quote_room(self.room, monday, monday + timedelta(days=1)).commission_rate, Decimal("8"))


class CancellationPolicyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = make_user()

    def booking(self, policy, start_in_days):
        room = make_room(prop=make_property(cancellation_policy=policy))
        return book_room(self.customer, room, days(start_in_days), days(start_in_days + 2))

    def test_policies(self):
        self.assertEqual(services.refund_percent(self.booking("flexible", 3)), Decimal("100"))
        self.assertEqual(services.refund_percent(self.booking("moderate", 10)), Decimal("100"))
        self.assertEqual(services.refund_percent(self.booking("moderate", 2)), Decimal("50"))
        self.assertEqual(services.refund_percent(self.booking("strict", 10)), Decimal("50"))
        self.assertEqual(services.refund_percent(self.booking("strict", 2)), Decimal("0"))
        self.assertEqual(services.refund_percent(self.booking("non_refundable", 30)), Decimal("0"))


class ConcurrentBookingTests(TransactionTestCase):
    """Two guests racing for the last unit: the row lock lets exactly one win."""

    def test_parallel_requests_cannot_double_book(self):
        if connection.vendor != "postgresql":
            self.skipTest("row-level locking test needs PostgreSQL")
        room = make_room(quantity=1)
        users = [make_user(), make_user(), make_user(), make_user()]
        results = []
        barrier = threading.Barrier(len(users))

        def attempt(user):
            try:
                barrier.wait()
                book_room(user, room, days(30), days(32))
                results.append("ok")
            except services.BookingError:
                results.append("rejected")
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(Booking.objects.filter(room_type=room).count(), 1)

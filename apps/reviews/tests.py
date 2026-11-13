from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.bookings import services as bs
from apps.bookings.models import Booking
from apps.core.testing import days, make_room, make_user

from .models import Review, refresh_property_rating


@override_settings(RATELIMIT_ENABLED=False)
class ReviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.guest = make_user()
        self.room = make_room()
        self.booking = bs.create_room_booking(customer=self.guest, room_type_id=self.room.pk, check_in=days(3), check_out=days(4), rooms=1,
                                              adults=1, children=0, guest=bs.GuestDetails("G", self.guest.email, "+250788000000", ""))
        self.client.force_login(self.guest)
        self.url = reverse("bookings:review", args=[self.booking.reference])
        self.data = {"rating": 5, "title": "Lovely", "body": "Great stay with friendly staff."}

    def test_only_completed_bookings_can_be_reviewed(self):
        self.client.post(self.url, self.data)
        self.assertFalse(Review.objects.exists())
        Booking.objects.filter(pk=self.booking.pk).update(status=Booking.Status.COMPLETED)
        self.client.post(self.url, self.data)
        self.assertEqual(Review.objects.get().status, Review.Status.PENDING)
        self.client.post(self.url, self.data)
        self.assertEqual(Review.objects.count(), 1)

    def test_other_users_cannot_review_booking(self):
        Booking.objects.filter(pk=self.booking.pk).update(status=Booking.Status.COMPLETED)
        self.client.force_login(make_user())
        self.assertEqual(self.client.post(self.url, self.data).status_code, 404)

    def test_rating_counts_only_approved_reviews(self):
        Booking.objects.filter(pk=self.booking.pk).update(status=Booking.Status.COMPLETED)
        review = Review.objects.create(booking=self.booking, property=self.room.property, author=self.guest, rating=4, title="t", body="b")
        refresh_property_rating(self.room.property)
        self.room.property.refresh_from_db()
        self.assertEqual(self.room.property.review_count, 0)
        review.status = Review.Status.APPROVED
        review.save()
        refresh_property_rating(self.room.property)
        self.room.property.refresh_from_db()
        self.assertEqual(self.room.property.review_count, 1)
        self.assertEqual(float(self.room.property.rating_avg), 4.0)

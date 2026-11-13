from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel

RATING = [MinValueValidator(1), MaxValueValidator(5)]


class Review(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Awaiting moderation")
        APPROVED = "approved", _("Published")
        REJECTED = "rejected", _("Rejected")

    booking = models.OneToOneField("bookings.Booking", on_delete=models.CASCADE, related_name="review")
    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="reviews")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=RATING)
    cleanliness = models.PositiveSmallIntegerField(validators=RATING, null=True, blank=True)
    service = models.PositiveSmallIntegerField(validators=RATING, null=True, blank=True)
    location = models.PositiveSmallIntegerField(validators=RATING, null=True, blank=True)
    value = models.PositiveSmallIntegerField(validators=RATING, null=True, blank=True)
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=3000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    moderation_note = models.CharField(max_length=255, blank=True)
    moderated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    vendor_reply = models.TextField(blank=True, max_length=2000)
    vendor_replied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating}★ {self.title}"


def refresh_property_rating(property_obj):
    agg = Review.objects.filter(property=property_obj, status=Review.Status.APPROVED).aggregate(a=Avg("rating"), c=Count("id"))
    property_obj.rating_avg = round(agg["a"] or 0, 2)
    property_obj.review_count = agg["c"]
    property_obj.__class__.objects.filter(pk=property_obj.pk).update(
        rating_avg=property_obj.rating_avg, review_count=property_obj.review_count
    )

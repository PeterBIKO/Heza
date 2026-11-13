import builtins
from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Min, Q
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import PERCENT_VALIDATORS, TimeStampedModel
from apps.core.validators import RandomFilename, validate_image_upload

MONEY = {"max_digits": 14, "decimal_places": 2}


class Category(models.TextChoices):
    HOTEL = "hotel", _("Hotel")
    LODGE = "lodge", _("Lodge")
    RESORT = "resort", _("Resort")
    GUESTHOUSE = "guesthouse", _("Guesthouse")
    APARTMENT = "apartment", _("Apartment")
    WEDDING_VENUE = "wedding_venue", _("Wedding venue")
    CONFERENCE_CENTER = "conference_center", _("Conference center")
    MEETING_ROOM = "meeting_room", _("Meeting room")
    GARDEN = "garden", _("Garden")
    HALL = "hall", _("Event hall")


LODGING_CATEGORIES = {Category.HOTEL, Category.LODGE, Category.RESORT, Category.GUESTHOUSE, Category.APARTMENT}
VENUE_CATEGORIES = {Category.WEDDING_VENUE, Category.CONFERENCE_CENTER, Category.MEETING_ROOM, Category.GARDEN, Category.HALL}

CATEGORY_ICONS = {
    "hotel": "building",
    "lodge": "tree",
    "resort": "water",
    "guesthouse": "house-heart",
    "apartment": "buildings",
    "wedding_venue": "balloon-heart",
    "conference_center": "easel2",
    "meeting_room": "people",
    "garden": "flower1",
    "hall": "bank",
}


class CancellationPolicy(models.TextChoices):
    FLEXIBLE = "flexible", _("Flexible — full refund up to 24 hours before arrival")
    MODERATE = "moderate", _("Moderate — full refund up to 5 days before, 50% after")
    STRICT = "strict", _("Strict — 50% refund up to 7 days before, none after")
    NON_REFUNDABLE = "non_refundable", _("Non-refundable")


class Amenity(models.Model):
    class Scope(models.TextChoices):
        PROPERTY = "property", _("Property")
        ROOM = "room", _("Room")
        VENUE = "venue", _("Venue")

    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=70, unique=True)
    icon = models.CharField(max_length=40, default="check2", help_text=_("Bootstrap icon name, e.g. wifi"))
    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.PROPERTY)

    class Meta:
        ordering = ["scope", "name"]
        verbose_name_plural = "amenities"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class PropertyQuerySet(models.QuerySet):
    def public(self):
        """Only verified properties of approved vendors are ever shown to the public."""
        return self.filter(status=Property.Status.VERIFIED, vendor__status="approved")


class Property(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending verification")
        VERIFIED = "verified", _("Verified")
        REJECTED = "rejected", _("Rejected")
        SUSPENDED = "suspended", _("Suspended")

    class PaymentMode(models.TextChoices):
        FULL = "full", _("Full payment at booking")
        DEPOSIT = "deposit", _("Deposit at booking, balance later")

    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.CASCADE, related_name="properties")
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    category = models.CharField(max_length=30, choices=Category.choices, db_index=True)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField()
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=80, db_index=True)
    district = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=2, default="RW")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    star_rating = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(5)])
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    check_in_time = models.TimeField(default=time(14, 0))
    check_out_time = models.TimeField(default=time(11, 0))
    house_rules = models.TextField(blank=True)
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="properties")
    cancellation_policy = models.CharField(
        max_length=20, choices=CancellationPolicy.choices, default=CancellationPolicy.MODERATE
    )
    payment_mode = models.CharField(max_length=10, choices=PaymentMode.choices, default=PaymentMode.FULL)
    deposit_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("30"), validators=PERCENT_VALIDATORS,
        help_text=_("Used when payment mode is deposit."),
    )
    allow_pay_later = models.BooleanField(
        default=False, help_text=_("Guests may request to pay at the property; you must approve each request.")
    )
    allow_modifications = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    review_note = models.TextField(blank=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    starting_price = models.DecimalField(**MONEY, null=True, blank=True, db_index=True)
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0"))
    review_count = models.PositiveIntegerField(default=0)

    objects = PropertyQuerySet.as_manager()

    class Meta:
        ordering = ["-is_featured", "name"]
        verbose_name_plural = "properties"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.name}-{self.city}")[:160] or "property"
            slug, n = base, 2
            while Property.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("public:property_detail", args=[self.slug])

    @builtins.property
    def is_public(self):
        return self.status == self.Status.VERIFIED and self.vendor.status == "approved"

    @builtins.property
    def is_venue_category(self):
        return self.category in VENUE_CATEGORIES

    @builtins.property
    def category_icon(self):
        return CATEGORY_ICONS.get(self.category, "building")

    @builtins.property
    def cover(self):
        imgs = getattr(self, "_prefetched_objects_cache", {}).get("images")
        if imgs is not None:
            return imgs[0] if imgs else None
        return self.images.first()

    @builtins.property
    def price_unit(self):
        return _("per event") if self.is_venue_category and not self.room_types.exists() else _("per night")

    def refresh_starting_price(self):
        room_min = self.room_types.filter(is_active=True).aggregate(m=Min("base_price"))["m"]
        venue_prices = []
        for v in self.venues.filter(is_active=True):
            venue_prices += [p for p in (v.hourly_price, v.half_day_price, v.full_day_price, v.event_price) if p]
        candidates = [p for p in [room_min, *venue_prices] if p]
        self.starting_price = min(candidates) if candidates else None
        Property.objects.filter(pk=self.pk).update(starting_price=self.starting_price)


class PropertyImage(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=RandomFilename("properties"), validators=[validate_image_upload])
    caption = models.CharField(max_length=140, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


class RoomType(TimeStampedModel):
    class RoomCategory(models.TextChoices):
        STANDARD = "standard", _("Standard")
        DELUXE = "deluxe", _("Deluxe")
        EXECUTIVE = "executive", _("Executive")
        SUITE = "suite", _("Suite")
        FAMILY = "family", _("Family")
        VILLA = "villa", _("Villa / cottage")
        STUDIO = "studio", _("Studio")
        APARTMENT = "apartment", _("Apartment")
        DORM = "dorm", _("Dormitory")

    class BedType(models.TextChoices):
        SINGLE = "single", _("Single")
        TWIN = "twin", _("Twin")
        DOUBLE = "double", _("Double")
        QUEEN = "queen", _("Queen")
        KING = "king", _("King")
        BUNK = "bunk", _("Bunk")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="room_types")
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=RoomCategory.choices, default=RoomCategory.STANDARD)
    description = models.TextField(blank=True)
    max_adults = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1)])
    max_children = models.PositiveSmallIntegerField(default=0)
    bed_type = models.CharField(max_length=10, choices=BedType.choices, default=BedType.DOUBLE)
    bed_count = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    size_sqm = models.PositiveSmallIntegerField(null=True, blank=True)
    base_price = models.DecimalField(_("nightly price"), **MONEY, validators=[MinValueValidator(Decimal("1"))])
    weekend_price = models.DecimalField(
        _("Fri/Sat nightly price"), **MONEY, null=True, blank=True, validators=[MinValueValidator(Decimal("1"))]
    )
    quantity = models.PositiveSmallIntegerField(_("number of units"), default=1, validators=[MinValueValidator(1)])
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="room_types")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "base_price"]

    def __str__(self):
        return f"{self.name} · {self.property.name}"

    @builtins.property
    def max_guests(self):
        return self.max_adults + self.max_children

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.property.refresh_starting_price()


class RoomImage(models.Model):
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=RandomFilename("rooms"), validators=[validate_image_upload])
    caption = models.CharField(max_length=140, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


class SeasonalRate(models.Model):
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="seasonal_rates")
    name = models.CharField(max_length=80, help_text=_("e.g. Gorilla trekking high season"))
    start_date = models.DateField()
    end_date = models.DateField(help_text=_("Inclusive"))
    nightly_price = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("1"))])
    min_nights = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["start_date"]
        constraints = [models.CheckConstraint(condition=Q(end_date__gte=models.F("start_date")), name="seasonal_dates_ordered")]

    def __str__(self):
        return f"{self.name} ({self.start_date} – {self.end_date})"


class RoomBlock(models.Model):
    """Vendor-closed inventory (maintenance, offline sales). end_date is exclusive like a check-out."""

    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="blocks")
    start_date = models.DateField()
    end_date = models.DateField()
    units = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    reason = models.CharField(max_length=140, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["start_date"]
        constraints = [models.CheckConstraint(condition=Q(end_date__gt=models.F("start_date")), name="roomblock_dates_ordered")]


class Venue(TimeStampedModel):
    class Setting(models.TextChoices):
        INDOOR = "indoor", _("Indoor")
        OUTDOOR = "outdoor", _("Outdoor")
        MIXED = "mixed", _("Indoor & outdoor")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="venues")
    name = models.CharField(max_length=120)
    setting = models.CharField(max_length=10, choices=Setting.choices, default=Setting.INDOOR)
    description = models.TextField(blank=True)
    capacity_seated = models.PositiveIntegerField(default=50)
    capacity_standing = models.PositiveIntegerField(default=80)
    area_sqm = models.PositiveIntegerField(null=True, blank=True)
    hourly_price = models.DecimalField(**MONEY, null=True, blank=True)
    half_day_price = models.DecimalField(**MONEY, null=True, blank=True)
    full_day_price = models.DecimalField(**MONEY, null=True, blank=True)
    event_price = models.DecimalField(_("whole-event price"), **MONEY, null=True, blank=True)
    min_hours = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1)])
    opening_time = models.TimeField(default=time(8, 0))
    closing_time = models.TimeField(default=time(23, 0))
    turnover_minutes = models.PositiveSmallIntegerField(
        default=60, help_text=_("Setup/cleanup buffer kept free between bookings")
    )
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="venues")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} · {self.property.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.property.refresh_starting_price()

    @builtins.property
    def max_capacity(self):
        return max(self.capacity_seated, self.capacity_standing)


class VenueImage(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=RandomFilename("venues"), validators=[validate_image_upload])
    caption = models.CharField(max_length=140, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


class PriceUnit(models.TextChoices):
    PER_EVENT = "per_event", _("per event")
    PER_GUEST = "per_guest", _("per guest")
    PER_HOUR = "per_hour", _("per hour")
    PER_ITEM = "per_item", _("per item")


class VenuePackage(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="packages")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    price = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0"))])
    unit = models.CharField(
        max_length=10, choices=[(PriceUnit.PER_EVENT, _("per event")), (PriceUnit.PER_GUEST, _("per guest"))],
        default=PriceUnit.PER_GUEST,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["price"]

    def __str__(self):
        return self.name


class VenueExtra(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="extras")
    name = models.CharField(max_length=120)
    price = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0"))])
    unit = models.CharField(max_length=10, choices=PriceUnit.choices, default=PriceUnit.PER_EVENT)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class VenueBlock(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="blocks")
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    reason = models.CharField(max_length=140, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["start_at"]
        constraints = [models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="venueblock_ordered")]


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "property")]
        ordering = ["-created_at"]


class Inquiry(TimeStampedModel):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="inquiries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="inquiries")
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    message = models.TextField(max_length=3000)
    is_resolved = models.BooleanField(default=False)
    reply = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "inquiries"

    def __str__(self):
        return f"{self.name} → {self.property}"

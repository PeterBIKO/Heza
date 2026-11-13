from datetime import date, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.bookings.availability import (
    room_availability,
    units_available,
    venue_day_slots,
    venue_is_free,
)
from apps.bookings.models import Booking
from apps.bookings.pricing import quote_room, quote_venue, venue_window
from apps.properties.models import Property, RoomType, Venue, VenueExtra, VenuePackage

MAX_CALENDAR_DAYS = 120


def _date(value, default=None):
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


class PropertySerializer(serializers.ModelSerializer):
    url = serializers.CharField(source="get_absolute_url")
    cover = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="get_category_display")

    class Meta:
        model = Property
        fields = ["id", "name", "slug", "url", "category", "category_label", "city", "district", "latitude", "longitude",
                  "star_rating", "starting_price", "rating_avg", "review_count", "cover", "tagline"]

    def get_cover(self, obj):
        c = obj.cover
        return c.image.url if c else None


class PropertySearchAPI(generics.ListAPIView):
    serializer_class = PropertySerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = Property.objects.public().prefetch_related("images")
        q = self.request.query_params.get("q", "").strip()[:80]
        if q:
            qs = qs.filter(city__icontains=q) | qs.filter(name__icontains=q)
        cat = self.request.query_params.get("category")
        if cat:
            qs = qs.filter(category=cat)
        return qs.order_by("-is_featured", "-rating_avg")


def _public_room(pk):
    room = get_object_or_404(RoomType.objects.select_related("property__vendor"), pk=pk, is_active=True)
    if not room.property.is_public:
        from django.http import Http404

        raise Http404
    return room


def _public_venue(pk):
    venue = get_object_or_404(Venue.objects.select_related("property__vendor"), pk=pk, is_active=True)
    if not venue.property.is_public:
        from django.http import Http404

        raise Http404
    return venue


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def room_calendar(request, pk):
    room = _public_room(pk)
    start = max(_date(request.query_params.get("start"), timezone.localdate()), timezone.localdate())
    end = _date(request.query_params.get("end"), start + timedelta(days=42))
    end = min(max(end, start + timedelta(days=1)), start + timedelta(days=MAX_CALENDAR_DAYS))
    avail = room_availability(room, start, end)
    return Response({"room": room.pk, "quantity": room.quantity, "days": {d.isoformat(): n for d, n in avail.items()}})


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def room_quote(request, pk):
    room = _public_room(pk)
    ci, co = _date(request.query_params.get("check_in")), _date(request.query_params.get("check_out"))
    try:
        rooms = max(int(request.query_params.get("rooms", 1)), 1)
    except ValueError:
        rooms = 1
    if not ci or not co or co <= ci or ci < timezone.localdate():
        return Response({"error": "Choose valid dates."}, status=400)
    if (co - ci).days > 60:
        return Response({"error": "Stays are limited to 60 nights."}, status=400)
    free = units_available(room, ci, co)
    quote = quote_room(room, ci, co, rooms, request.query_params.get("coupon", ""))
    return Response({"available_units": free, "available": free >= rooms, "nights": (co - ci).days, **quote.as_dict()})


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def venue_slots(request, pk):
    venue = _public_venue(pk)
    day = _date(request.query_params.get("date"), timezone.localdate())
    if day < timezone.localdate():
        return Response({"error": "Date is in the past."}, status=400)
    return Response(venue_day_slots(venue, day))


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def venue_quote(request, pk):
    venue = _public_venue(pk)
    p = request.query_params
    day = _date(p.get("date"))
    mode = p.get("mode", "")
    if not day or day < timezone.localdate():
        return Response({"error": "Choose a valid event date."}, status=400)
    try:
        guests = max(int(p.get("guests", 1)), 1)
        hours = int(p.get("hours") or 0) or None
        start_time = None
        if p.get("start_time"):
            h, m = p["start_time"].split(":")[:2]
            from datetime import time

            start_time = time(int(h), int(m))
        start_at, end_at = venue_window(venue, mode, day, start_time, hours)
    except (ValueError, TypeError) as exc:
        return Response({"error": str(exc) or "Invalid time."}, status=400)
    package = VenuePackage.objects.filter(pk=p.get("package") or 0, venue=venue, is_active=True).first()
    extras = []
    for extra in VenueExtra.objects.filter(venue=venue, is_active=True):
        qty = p.get(f"extra_{extra.pk}")
        if qty in (None, "", "0", "false"):
            continue
        qty = 1 if qty in ("on", "true") else int(qty) if str(qty).isdigit() else 0
        if qty:
            extras.append((extra, min(qty, 1000)))
    try:
        quote = quote_venue(venue, mode, start_at, end_at, guests, package, extras, p.get("coupon", ""))
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)
    free = venue_is_free(venue, start_at, end_at) and start_at > timezone.now()
    return Response({"available": free, "start": timezone.localtime(start_at).strftime("%H:%M"),
                     "end": timezone.localtime(end_at).strftime("%H:%M"), "capacity_ok": guests <= venue.max_capacity, **quote.as_dict()})


class BookingSerializer(serializers.ModelSerializer):
    property = serializers.CharField(source="property.name")
    listing = serializers.CharField(source="listing_name")

    class Meta:
        model = Booking
        fields = ["reference", "kind", "property", "listing", "status", "payment_status", "check_in", "check_out", "start_at", "end_at",
                  "guests", "total", "amount_paid", "currency", "created_at"]


class MyBookingsAPI(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.request.user.bookings.select_related("property", "room_type", "venue")

from datetime import timedelta

from django.utils import timezone

from .models import Booking


def _overlapping_room_bookings(room_type, start, end, exclude=None):
    qs = Booking.objects.holding_inventory().filter(room_type=room_type, check_in__lt=end, check_out__gt=start)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs


def room_availability(room_type, start, end, exclude=None):
    """Map each night in [start, end) to the number of free units."""
    bookings = list(_overlapping_room_bookings(room_type, start, end, exclude).values("check_in", "check_out", "rooms"))
    blocks = list(room_type.blocks.filter(start_date__lt=end, end_date__gt=start).values("start_date", "end_date", "units"))
    result = {}
    night = start
    while night < end:
        used = sum(b["rooms"] for b in bookings if b["check_in"] <= night < b["check_out"])
        blocked = sum(b["units"] for b in blocks if b["start_date"] <= night < b["end_date"])
        result[night] = max(room_type.quantity - used - blocked, 0)
        night += timedelta(days=1)
    return result


def units_available(room_type, check_in, check_out, exclude=None):
    if not room_type.is_active:
        return 0
    nights = room_availability(room_type, check_in, check_out, exclude)
    return min(nights.values()) if nights else 0


def venue_conflicts(venue, start_at, end_at, exclude=None):
    """Bookings or blocks colliding with [start_at, end_at) including the turnover buffer."""
    buffer = timedelta(minutes=venue.turnover_minutes)
    qs = Booking.objects.holding_inventory().filter(venue=venue, start_at__lt=end_at + buffer, end_at__gt=start_at - buffer)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    blocks = venue.blocks.filter(start_at__lt=end_at, end_at__gt=start_at)
    return qs, blocks


def venue_is_free(venue, start_at, end_at, exclude=None):
    if not venue.is_active:
        return False
    bookings, blocks = venue_conflicts(venue, start_at, end_at, exclude)
    return not bookings.exists() and not blocks.exists()


def venue_day_slots(venue, day):
    """Availability of each fixed booking option on a day, plus busy intervals for hourly picking."""
    from .pricing import venue_mode_price, venue_window

    slots = []
    for mode, label in Booking.VenueMode.choices:
        if mode == "hourly":
            continue
        price = venue_mode_price(venue, mode)
        if price is None:
            continue
        start, end = venue_window(venue, mode, day)
        slots.append(
            {
                "mode": mode,
                "label": str(label),
                "start": timezone.localtime(start).strftime("%H:%M"),
                "end": timezone.localtime(end).strftime("%H:%M"),
                "price": str(price),
                "available": venue_is_free(venue, start, end) and start > timezone.now(),
            }
        )
    day_start, day_end = venue_window(venue, "event", day)
    busy = []
    bookings, blocks = venue_conflicts(venue, day_start, day_end)
    for b in bookings:
        busy.append([timezone.localtime(b.start_at).strftime("%H:%M"), timezone.localtime(b.end_at).strftime("%H:%M")])
    for b in blocks:
        busy.append([timezone.localtime(b.start_at).strftime("%H:%M"), timezone.localtime(b.end_at).strftime("%H:%M")])
    return {"date": day.isoformat(), "slots": slots, "busy": sorted(busy), "hourly_price": str(venue.hourly_price or "")}


def property_has_availability(prop, check_in, check_out, guests=1):
    for rt in prop.room_types.filter(is_active=True):
        free = units_available(rt, check_in, check_out)
        if free and free * rt.max_guests >= guests:
            return True
    return False


def search_available_property_ids(props, check_in, check_out, guests=1):
    """Filter properties: lodging needs a room type with enough free units; venues need a free whole-day window."""
    from .pricing import venue_window

    ids = []
    for prop in props:
        if prop.room_types.filter(is_active=True).exists():
            if property_has_availability(prop, check_in, check_out, guests):
                ids.append(prop.pk)
                continue
        for venue in prop.venues.filter(is_active=True, capacity_standing__gte=guests) | prop.venues.filter(
            is_active=True, capacity_seated__gte=guests
        ):
            start, end = venue_window(venue, "event", check_in)
            if venue_is_free(venue, start, end) or venue_is_free(venue, *venue_window(venue, "half_day_am", check_in)):
                ids.append(prop.pk)
                break
    return ids


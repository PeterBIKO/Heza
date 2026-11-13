from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import CategoryCommission, PlatformSettings
from apps.properties.models import PriceUnit

ONE = Decimal("1")
HUNDRED = Decimal("100")


def money(value):
    return Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP)


def commission_rate_for(property_obj):
    vendor = property_obj.vendor
    if vendor.commission_rate is not None:
        return vendor.commission_rate
    override = CategoryCommission.objects.filter(category=property_obj.category).first()
    if override:
        return override.rate
    return PlatformSettings.load().commission_rate


@dataclass
class Quote:
    currency: str = "RWF"
    lines: list = field(default_factory=list)
    subtotal: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    deposit_percent: Decimal = HUNDRED
    deposit: Decimal = Decimal("0")
    coupon: object = None
    coupon_error: str = ""
    commission_rate: Decimal = Decimal("10")

    def add(self, label, amount, qty=1, unit_price=None):
        amount = money(amount)
        self.lines.append(
            {"label": str(label), "qty": qty, "unit_price": str(money(unit_price if unit_price is not None else amount)), "amount": str(amount)}
        )
        self.subtotal += amount

    def finalize(self, property_obj, coupon_code=""):
        settings_obj = PlatformSettings.load()
        if coupon_code:
            from .models import Coupon

            coupon = Coupon.objects.filter(code=coupon_code.strip().upper()).first()
            if coupon is None:
                self.coupon_error = _("We couldn't find that promo code.")
            else:
                ok, err = coupon.is_valid_for(property_obj, self.subtotal)
                if ok:
                    self.coupon = coupon
                    self.discount = coupon.discount_for(self.subtotal)
                else:
                    self.coupon_error = err
        taxable = self.subtotal - self.discount
        self.tax_rate = settings_obj.tax_rate
        if settings_obj.tax_inclusive:
            self.tax = money(taxable - taxable / (ONE + self.tax_rate / HUNDRED))
            self.total = money(taxable)
        else:
            self.tax = money(taxable * self.tax_rate / HUNDRED)
            self.total = money(taxable + self.tax)
        if property_obj.payment_mode == property_obj.PaymentMode.DEPOSIT:
            self.deposit_percent = property_obj.deposit_percent
        else:
            self.deposit_percent = HUNDRED
        self.deposit = money(self.total * self.deposit_percent / HUNDRED)
        self.commission_rate = commission_rate_for(property_obj)
        return self

    def as_dict(self):
        return {
            "currency": self.currency,
            "lines": self.lines,
            "subtotal": str(self.subtotal),
            "discount": str(self.discount),
            "tax_rate": str(self.tax_rate),
            "tax": str(self.tax),
            "total": str(self.total),
            "deposit_percent": str(self.deposit_percent),
            "deposit": str(self.deposit),
            "coupon": self.coupon.code if self.coupon else None,
            "coupon_error": str(self.coupon_error),
        }


def nightly_rate(room_type, night, seasonal=None):
    """Price for one night. Seasonal rates beat weekend rates, which beat the base rate."""
    seasonal = seasonal if seasonal is not None else list(room_type.seasonal_rates.all())
    for rate in seasonal:
        if rate.start_date <= night <= rate.end_date:
            return rate.nightly_price, rate.name
    if room_type.weekend_price and night.weekday() in (4, 5):
        return room_type.weekend_price, _("Weekend")
    return room_type.base_price, ""


def quote_room(room_type, check_in, check_out, rooms=1, coupon_code=""):
    quote = Quote()
    seasonal = list(room_type.seasonal_rates.filter(start_date__lte=check_out, end_date__gte=check_in))
    groups = {}
    night = check_in
    while night < check_out:
        price, label = nightly_rate(room_type, night, seasonal)
        key = (price, label)
        groups[key] = groups.get(key, 0) + 1
        night += timedelta(days=1)
    for (price, label), count in groups.items():
        name = f"{room_type.name} × {rooms} · {count} night{'s' if count != 1 else ''}"
        if label:
            name += f" ({label})"
        quote.add(name, price * count * rooms, qty=count * rooms, unit_price=price)
    return quote.finalize(room_type.property, coupon_code)


def venue_window(venue, mode, day, start_time=None, hours=None):
    """Return (start_at, end_at) aware datetimes for a venue booking mode on a given day."""
    tz = timezone.get_current_timezone()
    open_dt = timezone.make_aware(datetime.combine(day, venue.opening_time), tz)
    close_dt = timezone.make_aware(datetime.combine(day, venue.closing_time), tz)
    noon = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz) + timedelta(hours=13)
    if mode == "hourly":
        if start_time is None or not hours:
            raise ValueError(_("Choose a start time and number of hours."))
        start = timezone.make_aware(datetime.combine(day, start_time), tz)
        return start, start + timedelta(hours=int(hours))
    if mode == "half_day_am":
        return open_dt, min(open_dt + timedelta(hours=5), noon)
    if mode == "half_day_pm":
        start = max(noon + timedelta(hours=1), open_dt)
        return start, min(start + timedelta(hours=5), close_dt)
    if mode == "full_day":
        return open_dt, min(open_dt + timedelta(hours=10), close_dt)
    if mode == "event":
        return open_dt, close_dt
    raise ValueError(_("Unknown booking option."))


def venue_mode_price(venue, mode):
    return {
        "hourly": venue.hourly_price,
        "half_day_am": venue.half_day_price,
        "half_day_pm": venue.half_day_price,
        "full_day": venue.full_day_price,
        "event": venue.event_price,
    }.get(mode)


def quote_venue(venue, mode, start_at, end_at, guests, package=None, extras=None, coupon_code=""):
    """extras: list of (VenueExtra, quantity)."""
    quote = Quote()
    base = venue_mode_price(venue, mode)
    if base is None:
        raise ValueError(_("This venue does not offer that booking option."))
    hours = Decimal((end_at - start_at).total_seconds() / 3600)
    if mode == "hourly":
        quote.add(f"{venue.name} · {hours.normalize():f} h", base * hours, qty=float(hours), unit_price=base)
    else:
        from .models import Booking

        quote.add(f"{venue.name} · {Booking.VenueMode(mode).label}", base)
    if package:
        if package.unit == PriceUnit.PER_GUEST:
            quote.add(f"{package.name} × {guests} guests", package.price * guests, qty=guests, unit_price=package.price)
        else:
            quote.add(package.name, package.price)
    for extra, qty in extras or []:
        if qty <= 0:
            continue
        if extra.unit == PriceUnit.PER_GUEST:
            units = guests
        elif extra.unit == PriceUnit.PER_HOUR:
            units = int(hours.to_integral_value()) or 1
        elif extra.unit == PriceUnit.PER_ITEM:
            units = qty
        else:
            units = 1
        quote.add(f"{extra.name} ({extra.get_unit_display()})", extra.price * units, qty=units, unit_price=extra.price)
    return quote.finalize(venue.property, coupon_code)

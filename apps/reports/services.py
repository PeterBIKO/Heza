import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.utils import timezone

from apps.bookings.models import Booking
from apps.payments.models import LedgerEntry, Payment, Refund
from apps.properties.models import Property

ZERO = Decimal("0")
REPORT_KINDS = ["bookings", "revenue", "commission", "occupancy", "payments", "cancellations"]


def parse_range(request, default_days=30):
    today = timezone.localdate()
    try:
        end = date.fromisoformat(request.GET.get("end", ""))
    except ValueError:
        end = today
    try:
        start = date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        start = end - timedelta(days=default_days - 1)
    if start > end:
        start, end = end, start
    if (end - start).days > 731:
        start = end - timedelta(days=731)
    return start, end


def _aware(d, end=False):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(d + timedelta(days=1) if end else d, time.min), tz)


class Scope:
    def __init__(self, vendor=None, property_ids=None):
        self.vendor = vendor
        self.property_ids = property_ids

    def bookings(self):
        qs = Booking.objects.all()
        if self.vendor is not None:
            qs = qs.filter(vendor=self.vendor)
        if self.property_ids is not None:
            qs = qs.filter(property_id__in=self.property_ids)
        return qs

    def properties(self):
        qs = Property.objects.all()
        if self.vendor is not None:
            qs = qs.filter(vendor=self.vendor)
        if self.property_ids is not None:
            qs = qs.filter(pk__in=self.property_ids)
        return qs

    def payments(self):
        return Payment.objects.filter(booking__in=self.bookings())


def summary(scope, start, end):
    s, e = _aware(start), _aware(end, end=True)
    created = scope.bookings().filter(created_at__gte=s, created_at__lt=e)
    by_status = dict(created.values_list("status").annotate(n=Count("id")))
    total_created = sum(by_status.values())
    payments = scope.payments().filter(created_at__gte=s, created_at__lt=e).exclude(provider="offline")
    succ = payments.filter(status=Payment.Status.SUCCESSFUL).count()
    failed = payments.filter(status=Payment.Status.FAILED).count()
    collected = scope.payments().filter(status=Payment.Status.SUCCESSFUL, verified_at__gte=s, verified_at__lt=e).aggregate(t=Sum("amount"))["t"] or ZERO
    refunded = Refund.objects.filter(booking__in=scope.bookings(), status=Refund.Status.SUCCEEDED, processed_at__gte=s, processed_at__lt=e).aggregate(t=Sum("amount"))["t"] or ZERO
    commission = LedgerEntry.objects.filter(
        wallet__vendor__isnull=True, booking__in=scope.bookings(), created_at__gte=s, created_at__lt=e,
        entry_type__in=[LedgerEntry.EntryType.COMMISSION, LedgerEntry.EntryType.COMMISSION_REVERSAL],
    ).aggregate(t=Sum("amount"))["t"] or ZERO
    cancelled = by_status.get("cancelled", 0) + by_status.get("refunded", 0)
    occ = occupancy(scope, start, end)
    sold = sum(r["sold"] for r in occ)
    avail = sum(r["available"] for r in occ)
    return {
        "start": start, "end": end, "bookings": total_created, "by_status": by_status,
        "confirmed": by_status.get("confirmed", 0) + by_status.get("completed", 0),
        "cancelled": cancelled, "cancellation_rate": round(cancelled / total_created * 100, 1) if total_created else 0,
        "gross_collected": collected, "refunded": refunded, "net_revenue": collected - refunded, "commission": commission,
        "vendor_net": collected - refunded - commission,
        "payment_success_rate": round(succ / (succ + failed) * 100, 1) if succ + failed else None,
        "payments_successful": succ, "payments_failed": failed,
        "occupancy_rate": round(sold / avail * 100, 1) if avail else None, "room_nights_sold": sold, "room_nights_available": avail,
        "daily": daily_series(scope, start, end),
    }


def occupancy(scope, start, end):
    """Room-nights sold vs. available per property for [start, end]."""
    days = (end - start).days + 1
    end_excl = end + timedelta(days=1)
    rows = []
    for prop in scope.properties().prefetch_related("room_types"):
        capacity = sum(rt.quantity for rt in prop.room_types.all() if rt.is_active) * days
        if not capacity:
            continue
        sold = 0
        for b in scope.bookings().filter(property=prop, kind="room", status__in=["confirmed", "completed"],
                                         check_in__lt=end_excl, check_out__gt=start).values("check_in", "check_out", "rooms"):
            overlap = (min(b["check_out"], end_excl) - max(b["check_in"], start)).days
            sold += max(overlap, 0) * b["rooms"]
        rows.append({"property": prop.name, "city": prop.city, "sold": sold, "available": capacity,
                     "rate": round(sold / capacity * 100, 1)})
    return rows


def daily_series(scope, start, end):
    s, e = _aware(start), _aware(end, end=True)
    counts = {}
    for row in scope.bookings().filter(created_at__gte=s, created_at__lt=e).values_list("created_at", flat=True):
        d = timezone.localtime(row).date()
        counts[d] = counts.get(d, 0) + 1
    revenue = {}
    for amount, ts in scope.payments().filter(status="successful", verified_at__gte=s, verified_at__lt=e).values_list("amount", "verified_at"):
        d = timezone.localtime(ts).date()
        revenue[d] = revenue.get(d, ZERO) + amount
    days = (end - start).days + 1
    series = [{"date": start + timedelta(days=i), "bookings": counts.get(start + timedelta(days=i), 0),
               "revenue": revenue.get(start + timedelta(days=i), ZERO)} for i in range(days)]
    peak = max([x["revenue"] for x in series] or [ZERO]) or Decimal("1")
    for x in series:
        x["pct"] = int(x["revenue"] / peak * 100)
    return series


def rows_for(kind, scope, start, end):
    s, e = _aware(start), _aware(end, end=True)
    if kind == "bookings":
        header = ["Reference", "Created", "Property", "Listing", "Kind", "Guest", "Start", "End", "Guests", "Status", "Payment status", "Total", "Paid", "Refunded", "Currency"]
        rows = []
        for b in scope.bookings().filter(created_at__gte=s, created_at__lt=e).select_related("property", "room_type", "venue"):
            rows.append([b.reference, timezone.localtime(b.created_at).strftime("%Y-%m-%d %H:%M"), b.property.name, b.listing_name, b.kind, b.guest_name,
                         b.check_in or timezone.localtime(b.start_at).strftime("%Y-%m-%d %H:%M"),
                         b.check_out or timezone.localtime(b.end_at).strftime("%Y-%m-%d %H:%M"), b.guests, b.status, b.payment_status,
                         b.total, b.amount_paid, b.amount_refunded, b.currency])
        return header, rows
    if kind in ("revenue", "payments"):
        qs = scope.payments().filter(created_at__gte=s, created_at__lt=e).select_related("booking__property")
        if kind == "revenue":
            qs = qs.filter(status="successful")
        header = ["Payment ref", "Booking", "Property", "Provider", "Method", "Purpose", "Status", "Amount", "Currency", "Created", "Verified", "Failure reason"]
        rows = [[p.reference, p.booking.reference, p.booking.property.name, p.provider, p.payment_method, p.purpose, p.status, p.amount, p.currency,
                 timezone.localtime(p.created_at).strftime("%Y-%m-%d %H:%M"),
                 timezone.localtime(p.verified_at).strftime("%Y-%m-%d %H:%M") if p.verified_at else "", p.failure_reason] for p in qs]
        return header, rows
    if kind == "commission":
        header = ["Booking", "Property", "Vendor", "Commission %", "Paid", "Refunded", "Commission", "Currency"]
        qs = scope.bookings().filter(amount_paid__gt=0, created_at__gte=s, created_at__lt=e).select_related("property", "vendor")
        rows = [[b.reference, b.property.name, b.vendor.business_name, b.commission_rate, b.amount_paid, b.amount_refunded, b.commission_amount, b.currency] for b in qs]
        return header, rows
    if kind == "occupancy":
        header = ["Property", "City", "Room-nights sold", "Room-nights available", "Occupancy %"]
        return header, [[r["property"], r["city"], r["sold"], r["available"], r["rate"]] for r in occupancy(scope, start, end)]
    if kind == "cancellations":
        header = ["Reference", "Property", "Guest", "Cancelled at", "Reason", "Paid", "Refunded", "Status"]
        qs = scope.bookings().filter(Q(status__in=["cancelled", "refunded"]), cancelled_at__gte=s, cancelled_at__lt=e).select_related("property")
        rows = [[b.reference, b.property.name, b.guest_name, timezone.localtime(b.cancelled_at).strftime("%Y-%m-%d %H:%M"), b.cancel_reason,
                 b.amount_paid, b.amount_refunded, b.status] for b in qs]
        return header, rows
    raise ValueError(kind)


def csv_response(kind, scope, start, end, prefix="heza"):
    header, rows = rows_for(kind, scope, start, end)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{prefix}-{kind}-{start}-{end}.csv"'
    resp.write("\ufeff")
    writer = csv.writer(resp)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe_cell(c) for c in row])
    return resp


def _safe_cell(value):
    """Neutralise spreadsheet formula injection."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not s.lstrip("-").replace(".", "").isdigit() else s

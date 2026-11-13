from django.contrib import admin

from .models import Booking, BookingEvent, BookingExtra, Coupon


class EventInline(admin.TabularInline):
    model = BookingEvent
    extra = 0
    readonly_fields = ("actor", "from_status", "to_status", "message", "created_at")
    can_delete = False


class ExtraInline(admin.TabularInline):
    model = BookingExtra
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "property", "kind", "guest_name", "check_in", "start_at", "status", "payment_status", "total")
    list_filter = ("status", "payment_status", "kind")
    search_fields = ("reference", "guest_name", "guest_email", "property__name")
    raw_id_fields = ("customer", "property", "vendor", "room_type", "venue", "package", "coupon", "cancelled_by")
    readonly_fields = ("reference", "amount_paid", "amount_refunded", "price_breakdown")
    inlines = [ExtraInline, EventInline]


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "vendor", "percent_off", "amount_off", "times_used", "max_uses", "is_active")
    list_filter = ("is_active",)

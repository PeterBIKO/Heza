from django.contrib import admin

from .models import (
    Amenity,
    Favorite,
    Inquiry,
    Property,
    PropertyImage,
    RoomBlock,
    RoomImage,
    RoomType,
    SeasonalRate,
    Venue,
    VenueBlock,
    VenueExtra,
    VenueImage,
    VenuePackage,
)


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("name", "scope", "icon")
    list_filter = ("scope",)
    prepopulated_fields = {"slug": ("name",)}


class PropertyImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 0


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "category", "city", "status", "is_featured", "starting_price", "rating_avg")
    list_filter = ("status", "category", "city", "is_featured")
    search_fields = ("name", "city", "vendor__business_name")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("amenities",)
    inlines = [PropertyImageInline]


class SeasonalInline(admin.TabularInline):
    model = SeasonalRate
    extra = 0


class RoomImageInline(admin.TabularInline):
    model = RoomImage
    extra = 0


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "base_price", "quantity", "is_active")
    list_filter = ("category", "is_active")
    inlines = [SeasonalInline, RoomImageInline]


class PackageInline(admin.TabularInline):
    model = VenuePackage
    extra = 0


class ExtraInline(admin.TabularInline):
    model = VenueExtra
    extra = 0


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "setting", "capacity_seated", "full_day_price", "is_active")
    inlines = [PackageInline, ExtraInline]


admin.site.register(RoomBlock, list_display=("room_type", "start_date", "end_date", "units", "reason"))
admin.site.register(VenueBlock, list_display=("venue", "start_at", "end_at", "reason"))
admin.site.register(VenueImage)
admin.site.register(Favorite, list_display=("user", "property", "created_at"))
admin.site.register(Inquiry, list_display=("property", "name", "email", "is_resolved", "created_at"))

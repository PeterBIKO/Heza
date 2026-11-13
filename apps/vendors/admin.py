from django.contrib import admin

from .models import StaffInvite, StaffMembership, Vendor, VendorDocument


class DocumentInline(admin.TabularInline):
    model = VendorDocument
    extra = 0
    fields = ("doc_type", "original_name", "status", "note")
    readonly_fields = ("original_name",)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("business_name", "owner", "status", "commission_rate", "city", "submitted_at")
    list_filter = ("status", "city")
    search_fields = ("business_name", "legal_name", "tin", "email")
    inlines = [DocumentInline]
    raw_id_fields = ("owner", "reviewed_by")


@admin.register(StaffMembership)
class StaffMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "vendor", "role", "is_active")
    list_filter = ("role", "is_active")
    raw_id_fields = ("user",)


@admin.register(StaffInvite)
class StaffInviteAdmin(admin.ModelAdmin):
    list_display = ("email", "vendor", "role", "expires_at", "accepted_at", "revoked")
    exclude = ("token",)

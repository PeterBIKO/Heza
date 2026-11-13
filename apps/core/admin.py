from django.contrib import admin

from .models import AuditLog, CategoryCommission, PlatformSettings


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    list_display = ("commission_rate", "tax_rate", "tax_inclusive", "min_payout_amount")


admin.site.register(CategoryCommission, list_display=("category", "rate"))


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_type", "target_id", "ip_address")
    list_filter = ("action",)
    search_fields = ("action", "description", "target_id", "actor__email")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

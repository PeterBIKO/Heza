from django.contrib import admin

from .models import (
    LedgerEntry,
    Payment,
    Payout,
    Refund,
    SandboxTransaction,
    Wallet,
    WebhookEvent,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Money records are changed only through services so the ledger stays consistent."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ("reference", "booking", "provider", "purpose", "amount", "status", "created_at")
    list_filter = ("status", "provider", "purpose")
    search_fields = ("reference", "provider_transaction_id", "booking__reference")


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdmin):
    list_display = ("received_at", "provider", "event_id", "signature_valid", "processed", "result")
    list_filter = ("provider", "signature_valid", "processed")


@admin.register(Wallet)
class WalletAdmin(ReadOnlyAdmin):
    list_display = ("vendor", "currency", "balance", "updated_at")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "wallet", "entry_type", "amount", "balance_after", "booking")
    list_filter = ("entry_type",)


@admin.register(Refund)
class RefundAdmin(ReadOnlyAdmin):
    list_display = ("booking", "amount", "status", "created_at", "processed_at")
    list_filter = ("status",)


@admin.register(Payout)
class PayoutAdmin(ReadOnlyAdmin):
    list_display = ("vendor", "amount", "status", "created_at", "paid_at")
    list_filter = ("status",)


admin.site.register(SandboxTransaction, ReadOnlyAdmin)

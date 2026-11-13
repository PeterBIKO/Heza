from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "recipient", "event", "subject", "status", "is_read")
    list_filter = ("channel", "status", "event")
    search_fields = ("recipient", "subject")

from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("property", "author", "rating", "status", "created_at")
    list_filter = ("status", "rating")
    search_fields = ("title", "body", "property__name", "author__email")
    raw_id_fields = ("booking", "author", "moderated_by")

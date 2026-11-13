from django.conf import settings

from apps.properties.models import Category


def site(request):
    ctx = {
        "BRAND": "Heza",
        "CURRENCY": settings.HEZA_CURRENCY,
        "SUPPORT_EMAIL": settings.SUPPORT_EMAIL,
        "PROPERTY_CATEGORIES": Category.choices,
        "compare_ids": request.session.get("compare", []) if hasattr(request, "session") else [],
        "unread_notifications": 0,
        "nav_vendor": None,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["unread_notifications"] = user.notifications.filter(channel="in_app", is_read=False).count()
        if user.is_vendor_user:
            from apps.core.rbac import get_vendor_context

            ctx["nav_vendor"] = get_vendor_context(user)
    return ctx

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

STATUS_COLORS = {
    "pending": "warning", "confirmed": "success", "cancelled": "danger", "completed": "secondary",
    "refunded": "info", "expired": "light", "draft": "light", "approved": "success", "verified": "success",
    "rejected": "danger", "suspended": "dark", "successful": "success", "failed": "danger", "initiated": "light",
    "processing": "info", "succeeded": "success", "requested": "warning", "paid": "success", "unpaid": "light",
    "deposit_paid": "info", "partially_refunded": "info", "accepted": "success", "sent": "success", "skipped": "light",
}


@register.filter
def money(value, currency="RWF"):
    if value in (None, ""):
        return "—"
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        return value
    return f"{currency} {amount:,.0f}" if currency else f"{amount:,.0f}"


@register.filter
def status_badge(status, label=None):
    color = STATUS_COLORS.get(str(status), "secondary")
    text_class = " text-dark" if color in ("warning", "light", "info") else ""
    return format_html('<span class="badge rounded-pill bg-{}{} badge-status">{}</span>', color, text_class, label or str(status).replace("_", " ").title())


@register.simple_tag
def badge(status, label):
    return status_badge(status, label)


@register.filter
def stars(value):
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0
    full = int(v)
    half = 1 if v - full >= 0.5 else 0
    html = '<i class="bi bi-star-fill"></i>' * full + '<i class="bi bi-star-half"></i>' * half + '<i class="bi bi-star"></i>' * (5 - full - half)
    return mark_safe(f'<span class="hz-stars" aria-label="{v:.1f} out of 5">{html}</span>')


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Rebuild the current query string with overrides: {% qs page=2 %}"""
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    return "?" + params.urlencode() if params else "?"


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def percent_of(part, whole):
    try:
        return round(float(part) / float(whole) * 100) if float(whole) else 0
    except (TypeError, ValueError):
        return 0


@register.filter
def initials(user):
    name = getattr(user, "get_full_name", lambda: "")() or getattr(user, "email", "?")
    parts = [p for p in name.replace("@", " ").split() if p]
    return "".join(p[0] for p in parts[:2]).upper()


@register.filter
def can(vctx, perm):
    return bool(vctx) and vctx.can(perm)

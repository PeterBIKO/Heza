from django.conf import settings

from .models import AuditLog


def client_ip(request):
    if request is None:
        return None
    # Only trust X-Forwarded-For behind our own proxy, which overwrites it; otherwise clients can spoof it to dodge rate limits.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") if settings.USE_X_FORWARDED_FOR else None
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR")


def audit(action, *, actor=None, target=None, description="", request=None, **metadata):
    """Append an immutable audit record. Never raises into the caller's flow for bad metadata."""
    if actor is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        actor = request.user
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    clean_meta = {k: (v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v)) for k, v in metadata.items()}
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target.__class__.__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "") or ""),
        description=description[:2000],
        ip_address=client_ip(request),
        metadata=clean_meta,
    )

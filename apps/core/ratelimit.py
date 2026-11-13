"""Small cache-backed fixed-window rate limiter for sensitive endpoints (login, signup, reset, contact)."""
import functools
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.template.loader import render_to_string

from .audit import client_ip

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse(rate):
    count, per = rate.split("/")
    return int(count), _UNITS[per]


def is_limited(scope, ident, rate, increment=True):
    limit, window = _parse(rate)
    bucket = int(time.time() // window)
    key = f"rl:{scope}:{ident}:{bucket}"
    if increment:
        added = cache.add(key, 1, window + 5)
        current = 1 if added else cache.incr(key)
    else:
        current = cache.get(key, 0)
    return current > limit


def ratelimit(scope, rate="10/m", methods=("POST",)):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            if getattr(settings, "RATELIMIT_ENABLED", True) and request.method in methods:
                if is_limited(scope, client_ip(request) or "unknown", rate):
                    html = render_to_string("errors/429.html", request=request)
                    return HttpResponse(html, status=429)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator

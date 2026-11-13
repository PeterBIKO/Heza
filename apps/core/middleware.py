from django.conf import settings


class SecurityHeadersMiddleware:
    """Adds a Content-Security-Policy and Permissions-Policy. All JS/CSS is served from /static."""

    def __init__(self, get_response):
        self.get_response = get_response
        img_src = "'self' data: blob: https://*.tile.openstreetmap.org https://images.unsplash.com"
        self.csp = "; ".join(
            [
                "default-src 'self'",
                "script-src 'self'",
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
                "font-src 'self' https://fonts.gstatic.com data:",
                f"img-src {img_src}",
                "connect-src 'self'",
                "frame-ancestors 'none'",
                "form-action 'self' https://checkout.flutterwave.com https://*.flutterwave.com",
                "base-uri 'self'",
                "object-src 'none'",
            ]
        )

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/django-admin/"):
            response.setdefault("Content-Security-Policy", self.csp)
        response.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        if not settings.DEBUG:
            response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response

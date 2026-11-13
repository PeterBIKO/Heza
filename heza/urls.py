from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

admin.site.site_header = "Heza data admin"
admin.site.site_title = "Heza"

urlpatterns = [
    path("", include("apps.public.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("partner/", include("apps.vendors.urls")),
    path("bookings/", include("apps.bookings.urls")),
    path("payments/", include("apps.payments.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("admin-panel/", include("apps.adminpanel.urls")),
    path("api/", include("apps.api.urls")),
    path("django-admin/", admin.site.urls),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"

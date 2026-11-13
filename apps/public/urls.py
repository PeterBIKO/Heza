from django.urls import path

from . import views

app_name = "public"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("stays/<slug:slug>/", views.property_detail, name="property_detail"),
    path("stays/<slug:slug>/contact/", views.contact_vendor, name="contact_vendor"),
    path("favorites/", views.favorites, name="favorites"),
    path("favorites/<int:pk>/toggle/", views.favorite_toggle, name="favorite_toggle"),
    path("compare/", views.compare, name="compare"),
    path("compare/<int:pk>/toggle/", views.compare_toggle, name="compare_toggle"),
    path("compare/clear/", views.compare_clear, name="compare_clear"),
    path("about/", views.static_page, {"page": "about"}, name="about"),
    path("help/", views.static_page, {"page": "help"}, name="help"),
    path("terms/", views.static_page, {"page": "terms"}, name="terms"),
    path("privacy/", views.static_page, {"page": "privacy"}, name="privacy"),
    path("list-your-property/", views.static_page, {"page": "partners"}, name="partners"),
]

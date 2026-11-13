from django.urls import path

from . import views

app_name = "adminpanel"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("vendors/", views.vendors, name="vendors"),
    path("vendors/<int:pk>/", views.vendor_detail, name="vendor_detail"),
    path("vendors/<int:pk>/<str:action>/", views.vendor_action, name="vendor_action"),
    path("documents/<int:pk>/<str:action>/", views.document_action, name="document_action"),
    path("properties/", views.properties, name="properties"),
    path("properties/<int:pk>/", views.property_detail, name="property_detail"),
    path("properties/<int:pk>/<str:action>/", views.property_action, name="property_action"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/<str:action>/", views.user_action, name="user_action"),
    path("bookings/", views.bookings, name="bookings"),
    path("bookings/<str:reference>/", views.booking_detail, name="booking_detail"),
    path("payments/", views.payments, name="payments"),
    path("payments/<int:pk>/verify/", views.payment_verify, name="payment_verify"),
    path("webhooks/", views.webhooks, name="webhooks"),
    path("refunds/", views.refunds, name="refunds"),
    path("refunds/<int:pk>/<str:action>/", views.refund_action, name="refund_action"),
    path("payouts/", views.payouts, name="payouts"),
    path("payouts/<int:pk>/<str:action>/", views.payout_action, name="payout_action"),
    path("reviews/", views.reviews, name="reviews"),
    path("reviews/<int:pk>/<str:action>/", views.review_action, name="review_action"),
    path("coupons/", views.coupons, name="coupons"),
    path("coupons/<int:pk>/toggle/", views.coupon_toggle, name="coupon_toggle"),
    path("amenities/", views.amenities, name="amenities"),
    path("amenities/<int:pk>/delete/", views.amenity_delete, name="amenity_delete"),
    path("reports/", views.reports_view, name="reports"),
    path("settings/", views.settings_view, name="settings"),
    path("audit/", views.audit_log, name="audit"),
]

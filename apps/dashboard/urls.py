from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("properties/", views.property_list, name="properties"),
    path("properties/new/", views.property_create, name="property_create"),
    path("properties/<int:pk>/", views.property_edit, name="property_edit"),
    path("properties/<int:pk>/submit/", views.property_submit, name="property_submit"),
    path("properties/<int:pk>/images/", views.property_images, name="property_images"),
    path("properties/<int:pk>/rooms/new/", views.room_create, name="room_create"),
    path("properties/<int:pk>/venues/new/", views.venue_create, name="venue_create"),
    path("images/<str:kind>/<int:image_id>/", views.image_action, name="image_action"),
    path("rooms/<int:pk>/", views.room_edit, name="room_edit"),
    path("rooms/<str:kind>/<int:pk>/delete/", views.room_child_delete, name="room_child_delete"),
    path("venues/<int:pk>/", views.venue_edit, name="venue_edit"),
    path("venues/<str:kind>/<int:pk>/delete/", views.venue_child_delete, name="venue_child_delete"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("bookings/", views.booking_list, name="bookings"),
    path("bookings/<str:reference>/", views.booking_detail, name="booking_detail"),
    path("bookings/<str:reference>/<str:action>/", views.booking_action, name="booking_action"),
    path("wallet/", views.wallet, name="wallet"),
    path("staff/", views.staff, name="staff"),
    path("staff/<int:pk>/", views.staff_edit, name="staff_edit"),
    path("staff/invites/<int:pk>/<str:action>/", views.invite_action, name="invite_action"),
    path("reviews/", views.reviews, name="reviews"),
    path("reviews/<int:pk>/reply/", views.review_reply, name="review_reply"),
    path("inquiries/", views.inquiries, name="inquiries"),
    path("inquiries/<int:pk>/", views.inquiry_reply, name="inquiry_reply"),
    path("coupons/", views.coupons, name="coupons"),
    path("coupons/<int:pk>/toggle/", views.coupon_toggle, name="coupon_toggle"),
    path("reports/", views.reports_view, name="reports"),
    path("settings/", views.settings_view, name="settings"),
]

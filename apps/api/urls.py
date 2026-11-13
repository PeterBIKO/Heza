from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("properties/", views.PropertySearchAPI.as_view(), name="properties"),
    path("rooms/<int:pk>/calendar/", views.room_calendar, name="room_calendar"),
    path("rooms/<int:pk>/quote/", views.room_quote, name="room_quote"),
    path("venues/<int:pk>/slots/", views.venue_slots, name="venue_slots"),
    path("venues/<int:pk>/quote/", views.venue_quote, name="venue_quote"),
    path("me/bookings/", views.MyBookingsAPI.as_view(), name="my_bookings"),
]

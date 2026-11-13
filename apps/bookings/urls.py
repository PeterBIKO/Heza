from django.urls import path

from apps.reviews import views as review_views

from . import views

app_name = "bookings"

urlpatterns = [
    path("", views.my_bookings, name="mine"),
    path("new/room/<int:room_type_id>/", views.book_room, name="book_room"),
    path("new/venue/<int:venue_id>/", views.book_venue, name="book_venue"),
    path("<str:reference>/", views.booking_detail, name="detail"),
    path("<str:reference>/pay/", views.pay, name="pay"),
    path("<str:reference>/cancel/", views.cancel, name="cancel"),
    path("<str:reference>/modify/", views.modify, name="modify"),
    path("<str:reference>/review/", review_views.write_review, name="review"),
]

from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("return/<str:reference>/", views.payment_return, name="return"),
    path("webhooks/<str:provider>/", views.webhook, name="webhook"),
    path("sandbox/checkout/<str:txn_id>/", views.sandbox_checkout, name="sandbox_checkout"),
]

from django.urls import path

from . import views

app_name = "vendors"

urlpatterns = [
    path("register/", views.partner_register, name="register"),
    path("login/", views.PartnerLoginView.as_view(), name="login"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("onboarding/submit/", views.submit_application, name="submit_application"),
    path("documents/<int:pk>/", views.document_download, name="document_download"),
    path("documents/<int:pk>/delete/", views.document_delete, name="document_delete"),
    path("invite/<str:token>/", views.accept_invite, name="accept_invite"),
]

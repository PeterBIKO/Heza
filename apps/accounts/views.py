from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.audit import audit
from apps.core.ratelimit import ratelimit
from apps.notifications.models import Notification
from apps.notifications.services import send_verification_email

from .forms import (
    HezaPasswordChangeForm,
    HezaPasswordResetForm,
    HezaSetPasswordForm,
    LoginForm,
    ProfileForm,
    RegisterForm,
)
from .models import Role
from .tokens import read_email_token


def _dev_link(request, path):
    """In local development with the console email backend, surface the link so testers aren't stuck."""
    if settings.DEBUG and "console" in settings.EMAIL_BACKEND:
        request.session["dev_verify_link"] = path


@ratelimit("register", "8/h")
def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:after_login")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(role=Role.CUSTOMER)
        login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
        _dev_link(request, send_verification_email(user, request))
        audit("user.registered", actor=user, target=user, request=request, role=user.role)
        messages.success(request, _("Welcome to Heza! Check your inbox to confirm your email."))
        nxt = request.GET.get("next")
        if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
            return redirect(nxt)
        return redirect("accounts:verify_sent")
    return render(request, "accounts/register.html", {"form": form})


@method_decorator(ratelimit("login", "10/m"), name="dispatch")
class HezaLoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        audit("user.login", actor=form.get_user(), request=self.request)
        return response

    def form_invalid(self, form):
        identifier = self.request.POST.get("username", "")[:80]
        from .models import User

        u = User.objects.filter(email__iexact=identifier).first() or User.objects.filter(phone=identifier).first()
        if u is not None and u.is_suspended:
            form.errors.clear()
            form.add_error(None, _("This account is suspended. Contact %(e)s.") % {"e": settings.SUPPORT_EMAIL})
        return super().form_invalid(form)


@login_required
def after_login(request):
    user = request.user
    nxt = request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
        return redirect(nxt)
    if user.is_platform_admin:
        return redirect("adminpanel:overview")
    if user.is_vendor_user:
        return redirect("dashboard:overview")
    return redirect("public:home")


@require_POST
def logout_view(request):
    from django.contrib.auth import logout

    logout(request)
    messages.info(request, _("You have signed out."))
    return redirect("public:home")


def verify_sent(request):
    link = request.session.pop("dev_verify_link", None)
    return render(request, "accounts/verify_sent.html", {"dev_link": link})


def verify_email(request, token):
    user = read_email_token(token)
    if user is None:
        messages.error(request, _("That confirmation link is invalid or has expired. Request a new one below."))
        return redirect("accounts:verify_sent")
    if not user.is_email_verified:
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])
        audit("user.email_verified", actor=user, target=user, request=request)
    messages.success(request, _("Email confirmed. You're ready to book."))
    if request.user.is_authenticated:
        return redirect("accounts:after_login")
    return redirect("accounts:login")


@login_required
@require_POST
@ratelimit("resend_verify", "5/h")
def resend_verification(request):
    if request.user.is_email_verified:
        messages.info(request, _("Your email is already confirmed."))
        return redirect("accounts:after_login")
    _dev_link(request, send_verification_email(request.user, request))
    messages.success(request, _("We sent a new confirmation link to %(e)s.") % {"e": request.user.email})
    return redirect("accounts:verify_sent")


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Profile updated."))
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def password_change(request):
    form = HezaPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)
        audit("user.password_changed", request=request, target=request.user)
        messages.success(request, _("Password changed."))
        return redirect("accounts:profile")
    return render(request, "accounts/password_change.html", {"form": form})


@login_required
def notifications(request):
    qs = request.user.notifications.filter(channel=Notification.Channel.IN_APP)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "accounts/notifications.html", {"page": page})


@login_required
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    if n.link and url_has_allowed_host_and_scheme(n.link, {request.get_host()}):
        return redirect(n.link)
    return redirect("accounts:notifications")


@login_required
@require_POST
def notifications_read_all(request):
    request.user.notifications.filter(channel="in_app", is_read=False).update(is_read=True)
    return redirect(request.POST.get("next") or reverse("accounts:notifications"))


@method_decorator(ratelimit("pwreset", "5/h"), name="dispatch")
class HezaPasswordResetView(auth_views.PasswordResetView):
    form_class = HezaPasswordResetForm
    template_name = "accounts/password_reset.html"
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"
    subject_template_name = "emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
    extra_email_context = {"site_url": settings.SITE_URL}

    def form_valid(self, form):
        from apps.notifications.models import Notification as N

        response = super().form_valid(form)
        N.objects.create(recipient=form.cleaned_data["email"], channel="email", event="password_reset", subject="Password reset", body="(password reset email sent)")
        return response


class HezaPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    form_class = HezaSetPasswordForm
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

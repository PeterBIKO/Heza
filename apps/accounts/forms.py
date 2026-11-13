import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)
from django.utils.translation import gettext_lazy as _

from apps.core.forms import BootstrapMixin

from .models import User

PHONE_RE = re.compile(r"^\+?[0-9 ]{9,16}$")


def clean_phone_value(phone):
    phone = (phone or "").strip().replace(" ", "")
    if not phone:
        return phone
    if not PHONE_RE.match(phone):
        raise forms.ValidationError(_("Enter a valid phone number, e.g. +250788123456."))
    if phone.startswith("07") and len(phone) == 10:
        phone = "+250" + phone[1:]
    return phone


class LoginForm(BootstrapMixin, AuthenticationForm):
    username = forms.CharField(label=_("Email or phone"), max_length=254, widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}))
    error_messages = {
        "invalid_login": _("That email/phone and password don't match an active account."),
        "inactive": _("This account is inactive."),
    }


class RegisterForm(BootstrapMixin, forms.ModelForm):
    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text=_("At least 8 characters, not entirely numeric."))
    password2 = forms.CharField(label=_("Confirm password"), widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    accept_terms = forms.BooleanField(label=_("I agree to the Heza terms and privacy policy"))

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]
        labels = {"phone": _("Mobile number")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["phone"].required = True
        self.fields["phone"].widget.attrs["placeholder"] = "+250 788 123 456"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("An account with this email already exists. Try signing in."))
        return email

    def clean_phone(self):
        phone = clean_phone_value(self.cleaned_data.get("phone"))
        if phone and User.objects.filter(phone=phone).exists():
            raise forms.ValidationError(_("This phone number is already registered."))
        return phone

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("Passwords don't match."))
        if p1:
            user = User(email=data.get("email", ""), first_name=data.get("first_name", ""), last_name=data.get("last_name", ""))
            try:
                password_validation.validate_password(p1, user)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data

    def save(self, commit=True, role="customer"):
        user = super().save(commit=False)
        user.role = role
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class ProfileForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "marketing_opt_in"]
        labels = {"marketing_opt_in": _("Send me offers and travel inspiration")}

    def clean_phone(self):
        phone = clean_phone_value(self.cleaned_data.get("phone"))
        if phone and User.objects.filter(phone=phone).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("This phone number is already registered."))
        return phone


class HezaPasswordResetForm(BootstrapMixin, PasswordResetForm):
    pass


class HezaSetPasswordForm(BootstrapMixin, SetPasswordForm):
    pass


class HezaPasswordChangeForm(BootstrapMixin, PasswordChangeForm):
    pass

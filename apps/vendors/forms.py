from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import RegisterForm, clean_phone_value
from apps.core.forms import BootstrapMixin

from .models import StaffInvite, StaffMembership, Vendor, VendorDocument


class PartnerRegisterForm(RegisterForm):
    business_name = forms.CharField(label=_("Business name"), max_length=160)

    field_order = ["business_name", "first_name", "last_name", "email", "phone", "password1", "password2", "accept_terms"]


class VendorProfileForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["business_name", "legal_name", "tin", "email", "phone", "address", "city", "description", "logo"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get("phone"))


class PayoutDetailsForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["payout_method", "payout_momo_number", "payout_bank_name", "payout_account_name", "payout_account_number"]
        labels = {"payout_momo_number": _("MTN / Airtel MoMo number")}

    def clean(self):
        data = super().clean()
        if data.get("payout_method") == Vendor.PayoutMethod.MOMO and not data.get("payout_momo_number"):
            self.add_error("payout_momo_number", _("Enter the mobile money number that receives payouts."))
        if data.get("payout_method") == Vendor.PayoutMethod.BANK:
            for f in ("payout_bank_name", "payout_account_name", "payout_account_number"):
                if not data.get(f):
                    self.add_error(f, _("Required for bank payouts."))
        return data


class DocumentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = VendorDocument
        fields = ["doc_type", "file"]
        widgets = {"file": forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"})}


class InviteForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = StaffInvite
        fields = ["email", "role", "properties"]
        widgets = {"properties": forms.CheckboxSelectMultiple}
        help_texts = {"properties": _("Leave all unticked to give access to every property.")}

    def __init__(self, *args, vendor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.vendor = vendor
        self.fields["properties"].queryset = vendor.properties.all()
        self.fields["properties"].required = False

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if self.vendor.owner.email == email or StaffMembership.objects.filter(vendor=self.vendor, user__email__iexact=email, is_active=True).exists():
            raise forms.ValidationError(_("This person is already on your team."))
        return email


class MembershipForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = StaffMembership
        fields = ["role", "properties", "is_active"]
        widgets = {"properties": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["properties"].queryset = self.instance.vendor.properties.all()
        self.fields["properties"].required = False


class AcceptInviteForm(RegisterForm):
    def __init__(self, *args, invite=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].initial = invite.email
        self.fields["email"].disabled = True

    def clean_email(self):
        return self.fields["email"].initial

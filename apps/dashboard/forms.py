from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import clean_phone_value
from apps.bookings.models import Coupon
from apps.core.forms import (
    BootstrapMixin,
    DateInput,
    DateTimeInput,
    MultipleImageField,
    TimeInput,
)
from apps.core.validators import validate_image_upload
from apps.properties.models import (
    Amenity,
    Property,
    RoomBlock,
    RoomType,
    SeasonalRate,
    Venue,
    VenueBlock,
    VenueExtra,
    VenuePackage,
)


class PropertyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Property
        fields = [
            "name", "category", "tagline", "description", "address", "city", "district", "latitude", "longitude",
            "star_rating", "email", "phone", "check_in_time", "check_out_time", "amenities", "house_rules",
        ]
        widgets = {
            "amenities": forms.CheckboxSelectMultiple, "check_in_time": TimeInput(), "check_out_time": TimeInput(),
            "description": forms.Textarea(attrs={"rows": 6}), "house_rules": forms.Textarea(attrs={"rows": 3}),
            "latitude": forms.NumberInput(attrs={"step": "0.000001", "placeholder": "-1.9441"}),
            "longitude": forms.NumberInput(attrs={"step": "0.000001", "placeholder": "30.0619"}),
        }
        help_texts = {"latitude": _("Tip: right-click the place in OpenStreetMap → 'Show address' to copy coordinates.")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amenities"].queryset = Amenity.objects.filter(scope=Amenity.Scope.PROPERTY)
        self.fields["amenities"].required = False

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get("phone"))


class PolicyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Property
        fields = ["cancellation_policy", "payment_mode", "deposit_percent", "allow_pay_later", "allow_modifications"]
        labels = {"allow_modifications": _("Guests may change dates online (up to 24h before arrival)")}

    def clean(self):
        data = super().clean()
        if data.get("payment_mode") == Property.PaymentMode.DEPOSIT:
            pct = data.get("deposit_percent") or Decimal("0")
            if pct < 10 or pct >= 100:
                self.add_error("deposit_percent", _("Deposit must be between 10% and 99%."))
        return data


class ImagesForm(forms.Form):
    images = MultipleImageField(label=_("Add photos"), required=True)

    def clean_images(self):
        files = self.cleaned_data["images"]
        if len(files) > 12:
            raise forms.ValidationError(_("Upload up to 12 photos at a time."))
        for f in files:
            validate_image_upload(f)
        return files


class RoomTypeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = RoomType
        fields = ["name", "category", "description", "max_adults", "max_children", "bed_type", "bed_count", "size_sqm",
                  "base_price", "weekend_price", "quantity", "amenities", "is_active", "sort_order"]
        widgets = {"amenities": forms.CheckboxSelectMultiple, "description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amenities"].queryset = Amenity.objects.filter(scope=Amenity.Scope.ROOM)
        self.fields["amenities"].required = False


class SeasonalRateForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SeasonalRate
        fields = ["name", "start_date", "end_date", "nightly_price", "min_nights"]
        widgets = {"start_date": DateInput(), "end_date": DateInput()}

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", _("End date must be on or after the start date."))
        return data


class RoomBlockForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = RoomBlock
        fields = ["start_date", "end_date", "units", "reason"]
        widgets = {"start_date": DateInput(), "end_date": DateInput()}
        labels = {"end_date": _("Until (first night open again)"), "units": _("Units to close")}

    def __init__(self, *args, room_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.room_type = room_type

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] <= data["start_date"]:
            self.add_error("end_date", _("Must be after the start date."))
        if self.room_type and data.get("units") and data["units"] > self.room_type.quantity:
            self.add_error("units", _("You only have %(n)s units of this room.") % {"n": self.room_type.quantity})
        return data


class VenueForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Venue
        fields = ["name", "setting", "description", "capacity_seated", "capacity_standing", "area_sqm", "hourly_price",
                  "half_day_price", "full_day_price", "event_price", "min_hours", "opening_time", "closing_time",
                  "turnover_minutes", "amenities", "is_active"]
        widgets = {"amenities": forms.CheckboxSelectMultiple, "opening_time": TimeInput(), "closing_time": TimeInput(),
                   "description": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"hourly_price": _("Leave a price empty to not offer that option.")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amenities"].queryset = Amenity.objects.filter(scope=Amenity.Scope.VENUE)
        self.fields["amenities"].required = False

    def clean(self):
        data = super().clean()
        if not any(data.get(f) for f in ("hourly_price", "half_day_price", "full_day_price", "event_price")):
            raise forms.ValidationError(_("Set at least one price (hourly, half day, full day or whole event)."))
        if data.get("opening_time") and data.get("closing_time") and data["closing_time"] <= data["opening_time"]:
            self.add_error("closing_time", _("Closing time must be after opening time."))
        return data


class VenuePackageForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = VenuePackage
        fields = ["name", "description", "price", "unit", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class VenueExtraForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = VenueExtra
        fields = ["name", "price", "unit", "is_active"]


class VenueBlockForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = VenueBlock
        fields = ["start_at", "end_at", "reason"]
        widgets = {"start_at": DateTimeInput(), "end_at": DateTimeInput()}

    def clean(self):
        data = super().clean()
        if data.get("start_at") and data.get("end_at") and data["end_at"] <= data["start_at"]:
            self.add_error("end_at", _("Must be after the start."))
        return data


class CouponForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ["code", "description", "percent_off", "amount_off", "min_subtotal", "valid_from", "valid_until", "max_uses", "is_active"]
        widgets = {"valid_from": DateInput(), "valid_until": DateInput()}

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if Coupon.objects.filter(code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("This code is already in use."))
        return code

    def clean(self):
        data = super().clean()
        if bool(data.get("percent_off")) == bool(data.get("amount_off")):
            raise forms.ValidationError(_("Set either a percentage or a fixed amount off."))
        return data


class OfflinePaymentForm(BootstrapMixin, forms.Form):
    METHODS = [("cash", _("Cash")), ("pos", _("Card terminal (POS)")), ("momo", _("Mobile money to property")), ("bank", _("Bank transfer"))]
    amount = forms.DecimalField(min_value=1, decimal_places=0, max_digits=14)
    method = forms.ChoiceField(choices=METHODS)
    note = forms.CharField(required=False, max_length=200)


class PayoutRequestForm(BootstrapMixin, forms.Form):
    amount = forms.DecimalField(min_value=1, decimal_places=0, max_digits=14, label=_("Amount (RWF)"))


class ReplyForm(BootstrapMixin, forms.Form):
    reply = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)


class VendorCancelForm(BootstrapMixin, forms.Form):
    reason = forms.CharField(max_length=255, label=_("Reason shown to the guest"))

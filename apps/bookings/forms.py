from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import clean_phone_value
from apps.core.forms import BootstrapMixin, DateInput, TimeInput

from .models import Booking


class GuestFieldsMixin(forms.Form):
    guest_name = forms.CharField(label=_("Full name"), max_length=120)
    guest_email = forms.EmailField(label=_("Email"))
    guest_phone = forms.CharField(label=_("Mobile number"), max_length=20)
    special_requests = forms.CharField(label=_("Special requests (optional)"), required=False, max_length=2000,
                                       widget=forms.Textarea(attrs={"rows": 3}))
    coupon_code = forms.CharField(label=_("Promo code"), required=False, max_length=30)
    pay_later = forms.BooleanField(label=_("Request to pay at the property (the property must approve)"), required=False)

    def clean_guest_phone(self):
        return clean_phone_value(self.cleaned_data.get("guest_phone"))


class RoomBookingForm(BootstrapMixin, GuestFieldsMixin):
    check_in = forms.DateField(widget=DateInput())
    check_out = forms.DateField(widget=DateInput())
    rooms = forms.IntegerField(min_value=1, max_value=20, initial=1)
    adults = forms.IntegerField(min_value=1, max_value=60, initial=2)
    children = forms.IntegerField(min_value=0, max_value=40, initial=0)

    field_order = ["check_in", "check_out", "rooms", "adults", "children", "guest_name", "guest_email", "guest_phone",
                   "special_requests", "coupon_code", "pay_later"]

    def __init__(self, *args, room_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        if room_type is not None:
            self.fields["rooms"].max_value = room_type.quantity
            self.fields["rooms"].widget.attrs["max"] = room_type.quantity
            if not room_type.property.allow_pay_later:
                del self.fields["pay_later"]


class VenueBookingForm(BootstrapMixin, GuestFieldsMixin):
    day = forms.DateField(label=_("Event date"), widget=DateInput())
    mode = forms.ChoiceField(label=_("Booking option"), choices=Booking.VenueMode.choices)
    start_time = forms.TimeField(label=_("Start time"), required=False, widget=TimeInput())
    hours = forms.IntegerField(label=_("Hours"), required=False, min_value=1, max_value=16)
    guests = forms.IntegerField(min_value=1, max_value=5000)
    package = forms.ChoiceField(label=_("Package"), required=False)
    event_type = forms.CharField(label=_("Type of event"), required=False, max_length=80,
                                 widget=forms.TextInput(attrs={"placeholder": _("Wedding, conference, birthday…")}))

    field_order = ["day", "mode", "start_time", "hours", "guests", "package", "event_type"]

    def __init__(self, *args, venue=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.venue = venue
        from .pricing import venue_mode_price

        self.fields["mode"].choices = [(k, v) for k, v in Booking.VenueMode.choices if venue_mode_price(venue, k) is not None]
        self.fields["package"].choices = [("", _("No package — venue only"))] + [
            (str(p.pk), f"{p.name} · {p.price:,.0f} RWF {p.get_unit_display()}") for p in venue.packages.filter(is_active=True)
        ]
        self.extra_fields = []
        for extra in venue.extras.filter(is_active=True):
            name = f"extra_{extra.pk}"
            if extra.unit == "per_item":
                self.fields[name] = forms.IntegerField(label=extra.name, required=False, min_value=0, max_value=1000, initial=0,
                                                       help_text=f"{extra.price:,.0f} RWF {extra.get_unit_display()}")
            else:
                self.fields[name] = forms.BooleanField(label=extra.name, required=False,
                                                       help_text=f"{extra.price:,.0f} RWF {extra.get_unit_display()}")
            self.fields[name].widget.attrs["data-extra"] = extra.pk
            self.extra_fields.append(name)
        for name in self.extra_fields:
            css = "form-check-input" if isinstance(self.fields[name].widget, forms.CheckboxInput) else "form-control"
            self.fields[name].widget.attrs["class"] = css
        if not venue.property.allow_pay_later:
            del self.fields["pay_later"]

    def clean(self):
        data = super().clean()
        if data.get("mode") == "hourly":
            if not data.get("start_time"):
                self.add_error("start_time", _("Choose a start time."))
            if not data.get("hours"):
                self.add_error("hours", _("How many hours?"))
        return data

    def extras(self):
        out = {}
        for name in self.extra_fields:
            val = self.cleaned_data.get(name)
            qty = int(val) if not isinstance(val, bool) else (1 if val else 0)
            if qty:
                out[int(name.split("_")[1])] = qty
        return out

    def extra_bound_fields(self):
        return [self[name] for name in self.extra_fields]


class CancelForm(BootstrapMixin, forms.Form):
    reason = forms.CharField(label=_("Reason (optional)"), required=False, max_length=255)
    confirm = forms.BooleanField(label=_("I understand the cancellation policy and refund shown above"))


class ModifyRoomForm(BootstrapMixin, forms.Form):
    check_in = forms.DateField(widget=DateInput())
    check_out = forms.DateField(widget=DateInput())
    rooms = forms.IntegerField(min_value=1, max_value=20)
    adults = forms.IntegerField(min_value=1, max_value=60)
    children = forms.IntegerField(min_value=0, max_value=40)


class ModifyVenueForm(BootstrapMixin, forms.Form):
    day = forms.DateField(label=_("Event date"), widget=DateInput())
    mode = forms.ChoiceField(label=_("Booking option"), choices=Booking.VenueMode.choices)
    start_time = forms.TimeField(required=False, widget=TimeInput())
    hours = forms.IntegerField(required=False, min_value=1, max_value=16)
    guests = forms.IntegerField(min_value=1, max_value=5000)

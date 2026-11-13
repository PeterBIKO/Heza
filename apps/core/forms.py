from django import forms


class BootstrapMixin:
    """Applies Bootstrap classes to every widget so templates can render fields uniformly."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput,)):
                css = "form-check-input"
            elif isinstance(w, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                css = ""
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            if css:
                w.attrs["class"] = (w.attrs.get("class", "") + " " + css).strip()
            if self.errors.get(name):
                w.attrs["class"] = w.attrs.get("class", "") + " is-invalid"
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 4)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None, format="%Y-%m-%d"):
        super().__init__(attrs, format=format)


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, attrs=None, format="%H:%M"):
        super().__init__(attrs, format=format)


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, attrs=None, format="%Y-%m-%dT%H:%M"):
        super().__init__(attrs, format=format)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data]
        return [single(data, initial)] if data else []

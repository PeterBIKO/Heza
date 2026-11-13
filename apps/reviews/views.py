from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.bookings.models import Booking
from apps.core.forms import BootstrapMixin
from apps.notifications.services import notify_admins

from .models import Review

RATING_CHOICES = [(i, f"{i} ★") for i in range(5, 0, -1)]


class ReviewForm(BootstrapMixin, forms.ModelForm):
    rating = forms.TypedChoiceField(label=gettext_lazy("Overall"), choices=RATING_CHOICES, coerce=int, widget=forms.RadioSelect)
    cleanliness = forms.TypedChoiceField(choices=RATING_CHOICES, coerce=int, required=False, empty_value=None)
    service = forms.TypedChoiceField(choices=RATING_CHOICES, coerce=int, required=False, empty_value=None)
    location = forms.TypedChoiceField(choices=RATING_CHOICES, coerce=int, required=False, empty_value=None)
    value = forms.TypedChoiceField(label=gettext_lazy("Value for money"), choices=RATING_CHOICES, coerce=int, required=False, empty_value=None)

    class Meta:
        model = Review
        fields = ["rating", "cleanliness", "service", "location", "value", "title", "body"]
        labels = {"body": gettext_lazy("Your review")}
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}


def can_review(booking, user):
    return booking.customer_id == user.pk and booking.status == Booking.Status.COMPLETED and not Review.objects.filter(booking=booking).exists()


@login_required
def write_review(request, reference):
    booking = get_object_or_404(Booking.objects.select_related("property"), reference=reference, customer=request.user)
    if not can_review(booking, request.user):
        messages.info(request, _("Reviews open after a completed stay or event, once per booking."))
        return redirect(booking.get_absolute_url())
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        review = form.save(commit=False)
        review.booking = booking
        review.property = booking.property
        review.author = request.user
        review.save()
        from django.urls import reverse

        notify_admins("review_submitted", _("New review for %(p)s awaiting moderation") % {"p": booking.property}, reverse("adminpanel:reviews"))
        messages.success(request, _("Thank you! Your review will appear once our team checks it."))
        return redirect(booking.get_absolute_url())
    return render(request, "reviews/write.html", {"b": booking, "form": form})

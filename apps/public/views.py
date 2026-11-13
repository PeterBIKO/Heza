from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.bookings.availability import search_available_property_ids, units_available
from apps.bookings.pricing import quote_room
from apps.core.forms import BootstrapMixin
from apps.core.ratelimit import ratelimit
from apps.properties.models import (
    LODGING_CATEGORIES,
    VENUE_CATEGORIES,
    Amenity,
    Category,
    Favorite,
    Inquiry,
    Property,
    PropertyImage,
    RoomType,
    Venue,
)
from apps.reviews.models import Review

MAX_COMPARE = 4


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _public_qs():
    return Property.objects.public().select_related("vendor").prefetch_related(
        Prefetch("images", queryset=PropertyImage.objects.order_by("sort_order", "id"))
    )


def _favorite_ids(request):
    if request.user.is_authenticated:
        return set(request.user.favorites.values_list("property_id", flat=True))
    return set()


def home(request):
    props = _public_qs()
    featured = list(props.filter(is_featured=True, category__in=LODGING_CATEGORIES)[:8]) or list(props.filter(category__in=LODGING_CATEGORIES)[:8])
    venues = list(props.filter(category__in=VENUE_CATEGORIES).order_by("-is_featured", "-rating_avg")[:4])
    destinations = (
        Property.objects.public().values("city").annotate(n=Count("id")).order_by("-n")[:6]
    )
    dest_images = {}
    for d in destinations:
        p = props.filter(city=d["city"]).first()
        dest_images[d["city"]] = p.cover.image.url if p and p.cover else ""
    category_counts = dict(Property.objects.public().values_list("category").annotate(n=Count("id")))
    return render(request, "public/home.html", {
        "featured": featured, "venues": venues, "destinations": destinations, "dest_images": dest_images,
        "category_counts": category_counts, "fav_ids": _favorite_ids(request),
        "today": timezone.localdate(), "tomorrow": timezone.localdate() + timedelta(days=1),
    })


SORTS = {
    "recommended": ("-is_featured", "-rating_avg", "name"),
    "price_asc": ("starting_price", "name"),
    "price_desc": ("-starting_price", "name"),
    "rating": ("-rating_avg", "-review_count"),
    "newest": ("-created_at",),
}


def search(request):
    g = request.GET
    qs = _public_qs()
    q = g.get("q", "").strip()[:80]
    if q:
        qs = qs.filter(Q(city__icontains=q) | Q(district__icontains=q) | Q(name__icontains=q) | Q(address__icontains=q))
    cats = [c for c in g.getlist("category") if c in Category.values]
    group = g.get("type")
    if group == "stays":
        cats = cats or list(LODGING_CATEGORIES)
    elif group == "venues":
        cats = cats or list(VENUE_CATEGORIES)
    if cats:
        qs = qs.filter(category__in=cats)
    try:
        guests = max(int(g.get("guests") or 1), 1)
    except ValueError:
        guests = 1
    min_price, max_price = g.get("min_price"), g.get("max_price")
    if min_price and min_price.isdigit():
        qs = qs.filter(starting_price__gte=int(min_price))
    if max_price and max_price.isdigit():
        qs = qs.filter(starting_price__lte=int(max_price))
    stars = [int(s) for s in g.getlist("stars") if s.isdigit()]
    if stars:
        qs = qs.filter(star_rating__in=stars)
    rating = g.get("rating")
    if rating and rating.replace(".", "").isdigit():
        qs = qs.filter(rating_avg__gte=float(rating))
    amenities = g.getlist("amenity")
    for slug in amenities[:10]:
        qs = qs.filter(amenities__slug=slug)
    if guests > 1:
        qs = qs.filter(Q(room_types__max_adults__gte=1) | Q(venues__capacity_standing__gte=guests)).distinct()
    check_in, check_out = parse_date(g.get("check_in")), parse_date(g.get("check_out"))
    date_error = ""
    if check_in and check_out:
        if check_in < timezone.localdate() or check_out <= check_in:
            date_error = _("Check-out must be after check-in, and dates can't be in the past.")
        else:
            ids = search_available_property_ids(list(qs.distinct()), check_in, check_out, guests)
            qs = qs.filter(pk__in=ids)
    elif check_in and not check_out:
        check_out = check_in + timedelta(days=1)
    sort = g.get("sort", "recommended")
    qs = qs.distinct().order_by(*SORTS.get(sort, SORTS["recommended"]))
    page = Paginator(qs, 12).get_page(g.get("page"))
    map_points = [
        {"name": p.name, "lat": float(p.latitude), "lng": float(p.longitude), "url": p.get_absolute_url(),
         "price": str(p.starting_price or ""), "city": p.city}
        for p in page.object_list if p.latitude and p.longitude
    ]
    return render(request, "public/search.html", {
        "page": page, "total": page.paginator.count, "q": q, "cats": cats, "guests": guests, "check_in": check_in,
        "check_out": check_out, "sort": sort, "stars": stars, "amenities_selected": amenities,
        "all_amenities": Amenity.objects.filter(scope="property"), "map_points": map_points, "fav_ids": _favorite_ids(request),
        "date_error": date_error, "group": group, "min_price": min_price or "", "max_price": max_price or "", "rating": rating or "",
        "lodging_categories": [c for c in Category.choices if c[0] in LODGING_CATEGORIES],
        "venue_categories": [c for c in Category.choices if c[0] in VENUE_CATEGORIES],
    })


def _can_preview(user, prop):
    if not user.is_authenticated:
        return False
    if user.is_platform_admin:
        return True
    from apps.core.rbac import get_vendor_context

    ctx = get_vendor_context(user)
    return bool(ctx and ctx.vendor.pk == prop.vendor_id)


class InquiryForm(BootstrapMixin, forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot

    class Meta:
        model = Inquiry
        fields = ["name", "email", "phone", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 4, "placeholder": _("Ask about availability, group rates, dietary needs…")})}


def property_detail(request, slug):
    prop = get_object_or_404(
        Property.objects.select_related("vendor").prefetch_related(
            "images", "amenities",
            Prefetch("room_types", queryset=RoomType.objects.filter(is_active=True).prefetch_related("images", "amenities")),
            Prefetch("venues", queryset=Venue.objects.filter(is_active=True).prefetch_related("images", "packages", "extras", "amenities")),
        ),
        slug=slug,
    )
    preview = False
    if not prop.is_public:
        if not _can_preview(request.user, prop):
            raise Http404
        preview = True
    check_in, check_out = parse_date(request.GET.get("check_in")), parse_date(request.GET.get("check_out"))
    try:
        guests = max(int(request.GET.get("guests") or 2), 1)
    except ValueError:
        guests = 2
    dates_ok = bool(check_in and check_out and check_out > check_in and check_in >= timezone.localdate())
    rooms = []
    for rt in prop.room_types.all():
        entry = {"room": rt, "available": None, "quote": None}
        if dates_ok:
            entry["available"] = units_available(rt, check_in, check_out)
            if entry["available"]:
                entry["quote"] = quote_room(rt, check_in, check_out, 1)
        rooms.append(entry)
    reviews = prop.reviews.filter(status=Review.Status.APPROVED).select_related("author")[:20]
    initial = {}
    if request.user.is_authenticated:
        initial = {"name": request.user.get_full_name(), "email": request.user.email, "phone": request.user.phone}
    similar = _public_qs().filter(city=prop.city).exclude(pk=prop.pk)[:3]
    return render(request, "public/property_detail.html", {
        "p": prop, "preview": preview, "rooms": rooms, "venues": prop.venues.all(), "reviews": reviews,
        "check_in": check_in, "check_out": check_out, "guests": guests, "dates_ok": dates_ok,
        "inquiry_form": InquiryForm(initial=initial), "is_favorite": prop.pk in _favorite_ids(request),
        "in_compare": prop.pk in request.session.get("compare", []), "similar": similar, "fav_ids": _favorite_ids(request),
        "nights": (check_out - check_in).days if dates_ok else 0, "today": timezone.localdate(),
        "map_point": {"name": prop.name, "lat": float(prop.latitude), "lng": float(prop.longitude), "city": prop.city}
        if prop.latitude is not None and prop.longitude is not None else None,
    })


@require_POST
@ratelimit("inquiry", "5/h")
def contact_vendor(request, slug):
    prop = get_object_or_404(Property.objects.public(), slug=slug)
    form = InquiryForm(request.POST)
    if form.is_valid() and not form.cleaned_data.get("website"):
        inquiry = form.save(commit=False)
        inquiry.property = prop
        inquiry.user = request.user if request.user.is_authenticated else None
        inquiry.save()
        from apps.notifications.services import notify_inquiry

        notify_inquiry(inquiry)
        messages.success(request, _("Message sent to %(p)s. They'll reply to %(e)s.") % {"p": prop.name, "e": inquiry.email})
    else:
        messages.error(request, _("Please fill in your name, a valid email and a message."))
    return redirect(prop.get_absolute_url() + "#contact")


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", "")


def _back(request, fallback):
    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
        return redirect(nxt)
    return redirect(fallback)


@require_POST
def favorite_toggle(request, pk):
    if not request.user.is_authenticated:
        if _wants_json(request):
            return JsonResponse({"login_required": True}, status=401)
        return redirect_to_login(request.POST.get("next") or "/")
    prop = get_object_or_404(Property.objects.public(), pk=pk)
    fav, created = Favorite.objects.get_or_create(user=request.user, property=prop)
    if not created:
        fav.delete()
    if _wants_json(request):
        return JsonResponse({"favorite": created})
    messages.success(request, _("Saved to favourites.") if created else _("Removed from favourites."))
    return _back(request, prop.get_absolute_url())


@login_required
def favorites(request):
    favs = request.user.favorites.filter(property__in=Property.objects.public()).select_related("property").prefetch_related("property__images")
    return render(request, "public/favorites.html", {"favorites": favs, "fav_ids": _favorite_ids(request)})


@require_POST
def compare_toggle(request, pk):
    prop = get_object_or_404(Property.objects.public(), pk=pk)
    ids = list(request.session.get("compare", []))
    added = False
    if pk in ids:
        ids.remove(pk)
    elif len(ids) >= MAX_COMPARE:
        if _wants_json(request):
            return JsonResponse({"error": _("You can compare up to %(n)s places.") % {"n": MAX_COMPARE}}, status=400)
        messages.warning(request, _("You can compare up to %(n)s places. Remove one first.") % {"n": MAX_COMPARE})
        return _back(request, prop.get_absolute_url())
    else:
        ids.append(pk)
        added = True
    request.session["compare"] = ids
    if _wants_json(request):
        return JsonResponse({"in_compare": added, "count": len(ids)})
    messages.success(request, _("Added to compare.") if added else _("Removed from compare."))
    return _back(request, prop.get_absolute_url())


def compare(request):
    ids = request.session.get("compare", [])
    props = list(_public_qs().filter(pk__in=ids).prefetch_related("amenities", "room_types", "venues"))
    all_amenities = sorted({a for p in props for a in p.amenities.all()}, key=lambda a: a.name)
    rows = []
    for p in props:
        rooms = list(p.room_types.all())
        venues = list(p.venues.all())
        rows.append({
            "p": p, "amenity_ids": {a.pk for a in p.amenities.all()}, "room_count": len(rooms),
            "max_guests": max([r.max_guests for r in rooms] or [0]), "max_capacity": max([v.max_capacity for v in venues] or [0]),
        })
    return render(request, "public/compare.html", {"rows": rows, "all_amenities": all_amenities})


@require_POST
def compare_clear(request):
    request.session["compare"] = []
    return redirect("public:compare")


def static_page(request, page):
    templates = {"about": "public/about.html", "help": "public/help.html", "terms": "public/terms.html",
                 "privacy": "public/privacy.html", "partners": "public/partners.html"}
    if page not in templates:
        raise Http404
    return render(request, templates[page])

"""Seed realistic demo data: vendors, properties across Rwanda, rooms, venues, bookings paid through
the sandbox gateway (so wallets and ledger are consistent), reviews and coupons.

    python manage.py seed_demo            # idempotent: skips if demo data exists
    python manage.py seed_demo --reset    # delete demo vendors/users first
"""
import shutil
from datetime import time, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.bookings import services as bs
from apps.bookings.models import Booking, Coupon
from apps.payments import services as pay
from apps.payments.models import SandboxTransaction
from apps.properties.models import (
    Amenity,
    Property,
    PropertyImage,
    RoomImage,
    RoomType,
    SeasonalRate,
    Venue,
    VenueExtra,
    VenueImage,
    VenuePackage,
)
from apps.reviews.models import Review, refresh_property_rating
from apps.vendors.models import StaffMembership, Vendor

DEMO_PASSWORD = "HezaDemo!2026"
IMG_DIR = Path(settings.BASE_DIR) / "seed_assets" / "img"

AMENITIES = [
    ("Free Wi-Fi", "wifi", "property"), ("Swimming pool", "water", "property"), ("Restaurant", "cup-hot", "property"),
    ("Free parking", "p-circle", "property"), ("Airport shuttle", "airplane", "property"), ("Spa", "flower1", "property"),
    ("Fitness centre", "bicycle", "property"), ("Bar", "cup-straw", "property"), ("Garden", "tree", "property"),
    ("24h reception", "clock", "property"), ("Lake view", "water", "property"), ("Volcano view", "triangle", "property"),
    ("Backup generator", "lightning-charge", "property"), ("Breakfast included", "egg-fried", "property"),
    ("Air conditioning", "snow", "room"), ("Balcony", "door-open", "room"), ("Private bathroom", "droplet", "room"),
    ("Smart TV", "tv", "room"), ("Mini fridge", "box", "room"), ("Fireplace", "fire", "room"), ("Kitchenette", "egg", "room"),
    ("Work desk", "laptop", "room"),
    ("Projector", "projector", "venue"), ("PA system", "speaker", "venue"), ("Stage", "easel", "venue"),
    ("Catering kitchen", "basket", "venue"), ("Bridal room", "stars", "venue"), ("Air conditioned hall", "snow", "venue"),
    ("Video conferencing", "camera-video", "venue"), ("Ample parking", "car-front", "venue"),
]

VENDORS = [
    {
        "business_name": "Ikaze Hospitality Group", "legal_name": "Ikaze Hospitality Ltd", "tin": "108234561", "city": "Kigali",
        "address": "KG 7 Ave, Kacyiru", "email": "ops@ikaze.example", "phone": "+250788100200",
        "owner": ("amani@ikaze.example", "Amani", "Uwase", "+250788100201"),
        "properties": [
            {
                "name": "Kigali Hills Hotel", "category": "hotel", "city": "Kigali", "district": "Gasabo", "star_rating": 4,
                "tagline": "Calm rooms above the city, ten minutes from the Convention Centre",
                "address": "KG 9 Ave 12, Nyarutarama", "lat": "-1.944070", "lng": "30.104300", "featured": True,
                "images": ["04", "05", "38", "06"], "amenities": ["Free Wi-Fi", "Swimming pool", "Restaurant", "Free parking", "Airport shuttle", "Fitness centre", "24h reception", "Backup generator", "Breakfast included"],
                "policy": "moderate", "mode": "deposit", "deposit": 30, "pay_later": True,
                "description": "A contemporary 64-room hotel on the Nyarutarama ridge with views across Kigali's hills. Rooms are quiet and bright, the rooftop pool faces the sunset, and the restaurant serves Rwandan coffee and a generous breakfast buffet. Business travellers get a work desk in every room and a free shuttle to Kigali Convention Centre.",
                "rooms": [
                    {"name": "Deluxe King", "category": "deluxe", "bed": "king", "beds": 1, "adults": 2, "children": 1, "price": 95000, "weekend": 110000, "qty": 12, "size": 32, "images": ["05", "07"], "amen": ["Air conditioning", "Private bathroom", "Smart TV", "Work desk", "Mini fridge"]},
                    {"name": "Twin City View", "category": "standard", "bed": "twin", "beds": 2, "adults": 2, "children": 0, "price": 78000, "weekend": None, "qty": 8, "size": 28, "images": ["06"], "amen": ["Air conditioning", "Private bathroom", "Smart TV", "Work desk"]},
                    {"name": "Executive Suite", "category": "suite", "bed": "king", "beds": 1, "adults": 2, "children": 2, "price": 185000, "weekend": 210000, "qty": 3, "size": 58, "images": ["25", "26"], "amen": ["Air conditioning", "Balcony", "Private bathroom", "Smart TV", "Mini fridge", "Work desk"]},
                ],
                "seasonal": [("Year-end festive season", 20, 45, 125000)],
                "venues": [
                    {"name": "Imena Conference Room", "setting": "indoor", "seated": 120, "standing": 180, "area": 220, "hourly": 120000, "half": 380000, "full": 650000, "event": None, "images": ["14", "15"], "amen": ["Projector", "PA system", "Air conditioned hall", "Video conferencing"],
                     "packages": [("Full-day conference package", "Coffee breaks, buffet lunch, water and stationery", 28000, "per_guest")],
                     "extras": [("Simultaneous interpretation booth", 250000, "per_event"), ("Extra wireless microphone", 15000, "per_item")]},
                ],
            },
            {
                "name": "Nyungwe Canopy Lodge", "category": "lodge", "city": "Nyamasheke", "district": "Nyamasheke", "star_rating": 4,
                "tagline": "Wake up above the rainforest canopy, a short drive from the canopy walk",
                "address": "Gisakura, Nyungwe National Park edge", "lat": "-2.475400", "lng": "29.198900", "featured": True,
                "images": ["19", "23", "00", "34"], "amenities": ["Restaurant", "Free parking", "Garden", "Bar", "Free Wi-Fi", "Breakfast included"],
                "policy": "strict", "mode": "deposit", "deposit": 50, "pay_later": False,
                "description": "Twelve timber cottages on the edge of Nyungwe Forest, built on stilts so the terrace looks straight into the trees. Colobus monkeys visit at breakfast, guides meet you at reception for the canopy walk and chimpanzee tracking, and dinner is served by the fire.",
                "rooms": [
                    {"name": "Forest Cottage", "category": "villa", "bed": "queen", "beds": 1, "adults": 2, "children": 1, "price": 165000, "weekend": None, "qty": 8, "size": 40, "images": ["36", "37"], "amen": ["Fireplace", "Balcony", "Private bathroom"]},
                    {"name": "Family Cottage", "category": "family", "bed": "double", "beds": 2, "adults": 4, "children": 2, "price": 240000, "weekend": None, "qty": 4, "size": 62, "images": ["08"], "amen": ["Fireplace", "Balcony", "Private bathroom"]},
                ],
                "seasonal": [("Dry season peak", 200, 260, 195000)],
                "venues": [],
            },
        ],
    },
    {
        "business_name": "Lake Kivu Escapes", "legal_name": "Lake Kivu Escapes SARL", "tin": "109887102", "city": "Rubavu",
        "address": "Avenue de la Production, Gisenyi", "email": "hello@kivuescapes.example", "phone": "+250788300400",
        "owner": ("claudine@kivuescapes.example", "Claudine", "Mukamana", "+250788300401"),
        "properties": [
            {
                "name": "Kivu Sands Resort", "category": "resort", "city": "Rubavu", "district": "Rubavu", "star_rating": 5,
                "tagline": "Private beach, infinity pool and sunsets over Lake Kivu",
                "address": "Avenue de la Coopérative, Gisenyi beach", "lat": "-1.701900", "lng": "29.256600", "featured": True,
                "images": ["24", "01", "20", "39", "21"], "amenities": ["Swimming pool", "Spa", "Restaurant", "Bar", "Lake view", "Free Wi-Fi", "Free parking", "Breakfast included", "Garden"],
                "policy": "moderate", "mode": "full", "deposit": 100, "pay_later": False,
                "description": "Rwanda's lakeside escape: 40 rooms and villas on a private stretch of Gisenyi beach. Swim in the infinity pool, take a boat to Napoleon's Island, or book a massage in the lakeside spa. Grilled tilapia and Kivu sambaza are the house speciality.",
                "rooms": [
                    {"name": "Lake View Room", "category": "deluxe", "bed": "king", "beds": 1, "adults": 2, "children": 1, "price": 145000, "weekend": 170000, "qty": 16, "size": 36, "images": ["09", "05"], "amen": ["Air conditioning", "Balcony", "Private bathroom", "Smart TV"]},
                    {"name": "Beach Villa with Plunge Pool", "category": "villa", "bed": "king", "beds": 1, "adults": 2, "children": 2, "price": 320000, "weekend": 360000, "qty": 5, "size": 85, "images": ["22", "20"], "amen": ["Air conditioning", "Balcony", "Private bathroom", "Smart TV", "Mini fridge"]},
                ],
                "seasonal": [("Easter & Kwibohora holidays", 140, 155, 175000)],
                "venues": [
                    {"name": "Sunset Beach Lawn", "setting": "outdoor", "seated": 250, "standing": 400, "area": 1400, "hourly": None, "half": 900000, "full": 1500000, "event": 2200000, "images": ["32", "11"], "amen": ["PA system", "Bridal room", "Ample parking", "Catering kitchen"],
                     "packages": [("Beach wedding package", "Ceremony arch, chairs, white décor, 3-course dinner and cake", 45000, "per_guest")],
                     "extras": [("Live traditional Intore dancers", 400000, "per_event"), ("Fireworks over the lake", 650000, "per_event")]},
                ],
            },
            {
                "name": "Gisenyi Lakeside Apartments", "category": "apartment", "city": "Rubavu", "district": "Rubavu", "star_rating": 3,
                "tagline": "Self-catering apartments a two-minute walk from the beach",
                "address": "Rue du Marché 8, Gisenyi", "lat": "-1.697100", "lng": "29.258900", "featured": False,
                "images": ["17", "27", "28", "29"], "amenities": ["Free Wi-Fi", "Free parking", "Lake view", "Backup generator"],
                "policy": "flexible", "mode": "full", "deposit": 100, "pay_later": True,
                "description": "Spacious one- and two-bedroom apartments with full kitchens, fast Wi-Fi and lake-facing balconies. Ideal for families and remote workers staying a week or more.",
                "rooms": [
                    {"name": "One-Bedroom Apartment", "category": "studio", "bed": "queen", "beds": 1, "adults": 2, "children": 1, "price": 65000, "weekend": None, "qty": 6, "size": 48, "images": ["27"], "amen": ["Kitchenette", "Balcony", "Smart TV", "Work desk"]},
                    {"name": "Two-Bedroom Apartment", "category": "family", "bed": "double", "beds": 2, "adults": 4, "children": 2, "price": 98000, "weekend": None, "qty": 4, "size": 80, "images": ["28", "29"], "amen": ["Kitchenette", "Balcony", "Smart TV"]},
                ],
                "seasonal": [], "venues": [],
            },
        ],
    },
    {
        "business_name": "Virunga Stays", "legal_name": "Virunga Stays Ltd", "tin": "107665443", "city": "Musanze",
        "address": "NM 155 St, Musanze", "email": "book@virungastays.example", "phone": "+250788500600",
        "owner": ("eric@virungastays.example", "Eric", "Habimana", "+250788500601"),
        "properties": [
            {
                "name": "Volcano View Guesthouse", "category": "guesthouse", "city": "Musanze", "district": "Musanze", "star_rating": 3,
                "tagline": "Cosy rooms 20 minutes from the Volcanoes National Park gate",
                "address": "Kinigi road, Musanze", "lat": "-1.499800", "lng": "29.634900", "featured": True,
                "images": ["35", "23", "33"], "amenities": ["Free Wi-Fi", "Restaurant", "Volcano view", "Garden", "Free parking", "Breakfast included"],
                "policy": "moderate", "mode": "deposit", "deposit": 30, "pay_later": True,
                "description": "A family-run guesthouse with eight rooms, a fireplace lounge and a garden that looks across to Sabyinyo and Bisoke. Early breakfast and packed lunches for gorilla trekkers, and the owners can arrange drivers and permits.",
                "rooms": [
                    {"name": "Garden Double", "category": "standard", "bed": "double", "beds": 1, "adults": 2, "children": 0, "price": 55000, "weekend": None, "qty": 5, "size": 22, "images": ["07"], "amen": ["Private bathroom", "Fireplace"]},
                    {"name": "Volcano View Family Room", "category": "family", "bed": "queen", "beds": 2, "adults": 3, "children": 2, "price": 85000, "weekend": None, "qty": 3, "size": 34, "images": ["08", "36"], "amen": ["Private bathroom", "Fireplace", "Balcony"]},
                ],
                "seasonal": [("Gorilla trekking high season", 200, 270, 68000)],
                "venues": [],
            },
        ],
    },
    {
        "business_name": "Imena Events & Venues", "legal_name": "Imena Events Ltd", "tin": "110443218", "city": "Kigali",
        "address": "KK 15 Rd, Kicukiro", "email": "events@imena.example", "phone": "+250788700800",
        "owner": ("diane@imena.example", "Diane", "Ingabire", "+250788700801"),
        "properties": [
            {
                "name": "Rebero Garden Venue", "category": "wedding_venue", "city": "Kigali", "district": "Kicukiro", "star_rating": 0,
                "tagline": "Hilltop gardens for weddings of 50 to 600 guests",
                "address": "Rebero hill, Kicukiro", "lat": "-1.996500", "lng": "30.075100", "featured": True,
                "images": ["32", "12", "13", "30"], "amenities": ["Free parking", "Garden", "Backup generator"],
                "policy": "strict", "mode": "deposit", "deposit": 30, "pay_later": True,
                "description": "Landscaped gardens on Rebero hill with a gazebo for ceremonies, a covered reception terrace and panoramic views of Kigali at night. Our in-house planners handle décor, catering partners and the traditional gusaba setup.",
                "rooms": [],
                "venues": [
                    {"name": "Main Garden & Gazebo", "setting": "outdoor", "seated": 400, "standing": 600, "area": 2500, "hourly": None, "half": 1200000, "full": 2000000, "event": 2800000, "images": ["32", "33"], "amen": ["PA system", "Stage", "Bridal room", "Ample parking", "Catering kitchen"],
                     "packages": [("Gold wedding package", "Décor, chairs with covers, buffet dinner, soft drinks, MC and DJ", 38000, "per_guest"), ("Gusaba (introduction) package", "Traditional décor, ibyansi, seating for both families", 1500000, "per_event")],
                     "extras": [("Photo booth", 250000, "per_event"), ("Extra tent (100 guests)", 350000, "per_item"), ("Valet parking team", 180000, "per_event")]},
                    {"name": "Terrace Pavilion", "setting": "mixed", "seated": 150, "standing": 220, "area": 600, "hourly": 150000, "half": 550000, "full": 900000, "event": None, "images": ["12", "13"], "amen": ["PA system", "Catering kitchen"],
                     "packages": [("Birthday & anniversary package", "Balloon décor, cake table, finger food", 18000, "per_guest")],
                     "extras": [("DJ with lights", 300000, "per_event")]},
                ],
            },
            {
                "name": "Kigali Business Hub", "category": "conference_center", "city": "Kigali", "district": "Nyarugenge", "star_rating": 0,
                "tagline": "Meeting rooms and a 300-seat auditorium in the CBD",
                "address": "KN 4 Ave, City Centre", "lat": "-1.948500", "lng": "30.059300", "featured": False,
                "images": ["14", "16", "15"], "amenities": ["Free Wi-Fi", "Restaurant", "Backup generator", "24h reception"],
                "policy": "moderate", "mode": "full", "deposit": 100, "pay_later": True,
                "description": "Fibre internet, backup power and professional AV in the heart of Kigali. Book a boardroom by the hour or the full auditorium for launches, trainings and AGMs.",
                "rooms": [],
                "venues": [
                    {"name": "Inzozi Auditorium", "setting": "indoor", "seated": 300, "standing": 350, "area": 450, "hourly": 250000, "half": 800000, "full": 1400000, "event": None, "images": ["14"], "amen": ["Projector", "PA system", "Stage", "Air conditioned hall", "Video conferencing"],
                     "packages": [("Training day package", "2 coffee breaks and lunch", 15000, "per_guest")],
                     "extras": [("Live-streaming crew", 450000, "per_event")]},
                    {"name": "Boardroom 1", "setting": "indoor", "seated": 14, "standing": 20, "area": 45, "hourly": 35000, "half": 120000, "full": 200000, "event": None, "images": ["15", "16"], "amen": ["Projector", "Video conferencing", "Air conditioned hall"],
                     "packages": [], "extras": [("Coffee & pastries", 5000, "per_guest")]},
                ],
            },
            {
                "name": "Huye Heritage Hall", "category": "hall", "city": "Huye", "district": "Huye", "star_rating": 0,
                "tagline": "A grand hall near the National Museum for graduations and receptions",
                "address": "Avenue de l'Université, Huye", "lat": "-2.596700", "lng": "29.739400", "featured": False,
                "images": ["10", "30"], "amenities": ["Free parking", "Backup generator"],
                "policy": "flexible", "mode": "deposit", "deposit": 40, "pay_later": True,
                "description": "A 500-seat hall with a stage, dressing rooms and a catering kitchen, popular for university graduations, weddings and community events in the Southern Province.",
                "rooms": [],
                "venues": [
                    {"name": "Grand Hall", "setting": "indoor", "seated": 500, "standing": 700, "area": 900, "hourly": 90000, "half": 400000, "full": 700000, "event": 950000, "images": ["10"], "amen": ["Stage", "PA system", "Catering kitchen", "Ample parking"],
                     "packages": [("Graduation party package", "Décor in your colours, buffet, soft drinks", 12000, "per_guest")], "extras": []},
                ],
            },
        ],
    },
    {
        "business_name": "Karongi Lakeshore Lodge", "legal_name": "Karongi Lakeshore Ltd", "tin": "111203987", "city": "Karongi",
        "address": "Kibuye town", "email": "stay@karongilodge.example", "phone": "+250788900100",
        "owner": ("jean@karongilodge.example", "Jean", "Nshimiyimana", "+250788900101"),
        "properties": [
            {
                "name": "Karongi Lakeshore Lodge", "category": "lodge", "city": "Karongi", "district": "Karongi", "star_rating": 3,
                "tagline": "Terraced cottages above the bays of Kibuye",
                "address": "Bethanie road, Kibuye", "lat": "-2.060800", "lng": "29.348500", "featured": False,
                "images": ["21", "02", "03"], "amenities": ["Lake view", "Restaurant", "Bar", "Garden", "Free parking"],
                "policy": "flexible", "mode": "full", "deposit": 100, "pay_later": True,
                "description": "Ten stone cottages stepping down to Lake Kivu, with kayaks, boat trips to Amahoro Island and the best brochettes in Kibuye.",
                "rooms": [
                    {"name": "Lake Cottage", "category": "villa", "bed": "queen", "beds": 1, "adults": 2, "children": 1, "price": 72000, "weekend": 85000, "qty": 10, "size": 30, "images": ["37"], "amen": ["Balcony", "Private bathroom"]},
                ],
                "seasonal": [], "venues": [],
            },
        ],
    },
]

CUSTOMERS = [
    ("guest@heza.example", "Grace", "Umutoni", "+250788111222"),
    ("kevin.m@heza.example", "Kevin", "Mugisha", "+250788333444"),
    ("aline.k@heza.example", "Aline", "Keza", "+250788555666"),
    ("sam.okello@heza.example", "Samuel", "Okello", "+256772123456"),
]

REVIEWS = [
    (5, "Perfect weekend", "Staff remembered our names from day one. The room was spotless and breakfast was excellent."),
    (4, "Great location", "Easy to reach, comfortable beds and fast Wi-Fi. The restaurant can get busy at dinner."),
    (5, "Our wedding was magical", "The team handled everything, from décor to timing. Guests still talk about the view."),
    (4, "Would come back", "Quiet, friendly and good value. Hot water could be faster in the mornings."),
    (5, "Unforgettable sunsets", "Watching the sun go down over the lake from the terrace was the highlight of our trip."),
]


class QuietSMS:
    channel = "sms"

    def send(self, to, body):
        return "seed"


class QuietWhatsApp(QuietSMS):
    channel = "whatsapp"


class Command(BaseCommand):
    help = "Create demo users, vendors, properties and bookings."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo data first")

    def handle(self, *args, **opts):
        quiet = {
            "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
            "SMS_BACKEND": "apps.core.management.commands.seed_demo.QuietSMS",
            "WHATSAPP_BACKEND": "apps.core.management.commands.seed_demo.QuietWhatsApp",
        }
        with override_settings(**quiet):
            if opts["reset"]:
                self.reset()
            if Vendor.objects.filter(email__endswith=".example").exists():
                self.stdout.write(self.style.WARNING("Demo data already present. Use --reset to recreate."))
                return
            self.amenities = self.make_amenities()
            self.make_people()
            for spec in VENDORS:
                self.make_vendor(spec)
            self.make_pending_vendor()
            self.make_bookings()
            self.make_coupons()
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(
            f"  Admin:      admin@heza.example / {DEMO_PASSWORD}\n"
            f"  Vendor:     amani@ikaze.example / {DEMO_PASSWORD}  (also diane@imena.example, claudine@kivuescapes.example)\n"
            f"  Reception:  reception@ikaze.example / {DEMO_PASSWORD}\n"
            f"  Guest:      guest@heza.example / {DEMO_PASSWORD}\n"
            f"  Promo code: KARIBU10"
        )

    # --- helpers -------------------------------------------------------------

    def reset(self):
        from apps.core.models import AuditLog
        from apps.notifications.models import Notification
        from apps.payments.models import (
            LedgerEntry,
            Payment,
            Payout,
            Refund,
            Wallet,
            WebhookEvent,
        )

        demo_users = User.objects.filter(email__endswith="heza.example") | User.objects.filter(email__endswith=".example")
        vendors = Vendor.objects.filter(email__endswith=".example")
        bookings = Booking.objects.filter(vendor__in=vendors)
        with transaction.atomic():
            Review.objects.filter(booking__in=bookings).delete()
            LedgerEntry.objects.filter(wallet__vendor__in=vendors).delete()
            LedgerEntry.objects.filter(booking__in=bookings).delete()
            Payout.objects.filter(vendor__in=vendors).delete()
            Refund.objects.filter(booking__in=bookings).delete()
            WebhookEvent.objects.filter(payment__booking__in=bookings).delete()
            refs = list(Payment.objects.filter(booking__in=bookings).values_list("reference", flat=True))
            SandboxTransaction.objects.filter(tx_ref__in=refs).delete()
            Payment.objects.filter(booking__in=bookings).delete()
            bookings.delete()
            Wallet.objects.filter(vendor__in=vendors).delete()
            platform = Wallet.objects.filter(vendor__isnull=True).first()
            if platform:
                platform.balance = sum((e.amount for e in platform.entries.all()), Decimal("0"))
                platform.save()
            Coupon.objects.filter(code__in=["KARIBU10", "IKAZE5000", "WEDDING15"]).delete()
            vendors.delete()
            Notification.objects.filter(user__in=demo_users).delete()
            AuditLog.objects.filter(actor__in=demo_users).delete()
            demo_users.delete()
        for folder in ("properties", "rooms", "venues"):
            shutil.rmtree(Path(settings.MEDIA_ROOT) / folder, ignore_errors=True)
        self.stdout.write("Removed previous demo data.")

    def make_amenities(self):
        out = {}
        for name, icon, scope in AMENITIES:
            obj, _ = Amenity.objects.get_or_create(name=name, scope=scope, defaults={"icon": icon})
            out[(name, scope)] = obj
        return out

    def amen(self, names, scope):
        return [self.amenities[(n, scope)] for n in names if (n, scope) in self.amenities]

    def user(self, email, first, last, phone, role, **extra):
        u = User.objects.filter(email=email).first()
        if u:
            return u
        u = User.objects.create_user(email=email, password=DEMO_PASSWORD, first_name=first, last_name=last, phone=phone,
                                     role=role, is_email_verified=True, **extra)
        return u

    def make_people(self):
        if not User.objects.filter(email="admin@heza.example").exists():
            User.objects.create_superuser(email="admin@heza.example", password=DEMO_PASSWORD, first_name="Heza", last_name="Admin", phone="+250788000000")
        self.customers = [self.user(e, first, last, p, Role.CUSTOMER) for e, first, last, p in CUSTOMERS]

    def attach(self, model, fk, keys):
        for i, key in enumerate(keys):
            path = IMG_DIR / f"{key}.jpg"
            if not path.exists():
                continue
            with path.open("rb") as fh:
                obj = model(sort_order=i, **fk)
                obj.image.save(f"{key}.jpg", File(fh), save=False)
                obj.save()

    def make_vendor(self, spec):
        email, first, last, phone = spec["owner"]
        owner = self.user(email, first, last, phone, Role.VENDOR_OWNER)
        now = timezone.now()
        vendor = Vendor.objects.create(
            owner=owner, business_name=spec["business_name"], legal_name=spec["legal_name"], tin=spec["tin"], email=spec["email"],
            phone=spec["phone"], address=spec["address"], city=spec["city"], status=Vendor.Status.APPROVED,
            payout_method=Vendor.PayoutMethod.MOMO, payout_momo_number=phone, submitted_at=now - timedelta(days=60),
            reviewed_at=now - timedelta(days=58), description=f"{spec['business_name']} — verified Heza partner.",
        )
        if spec["business_name"].startswith("Ikaze"):
            rec = self.user("reception@ikaze.example", "Olivier", "Niyonzima", "+250788100299", Role.RECEPTIONIST)
            StaffMembership.objects.create(vendor=vendor, user=rec, role=Role.RECEPTIONIST)
            mgr = self.user("manager@ikaze.example", "Sandrine", "Iradukunda", "+250788100298", Role.PROPERTY_MANAGER)
            StaffMembership.objects.create(vendor=vendor, user=mgr, role=Role.PROPERTY_MANAGER)
        for p in spec["properties"]:
            self.make_property(vendor, p)

    def make_property(self, vendor, p):
        is_venue = not p["rooms"]
        prop = Property.objects.create(
            vendor=vendor, name=p["name"], category=p["category"], tagline=p["tagline"], description=p["description"],
            address=p["address"], city=p["city"], district=p["district"], latitude=Decimal(p["lat"]), longitude=Decimal(p["lng"]),
            star_rating=p["star_rating"], email=vendor.email, phone=vendor.phone, status=Property.Status.VERIFIED,
            is_featured=p["featured"], cancellation_policy=p["policy"], payment_mode=p["mode"], deposit_percent=Decimal(p["deposit"]),
            allow_pay_later=p["pay_later"], check_in_time=time(9, 0) if is_venue else time(14, 0), check_out_time=time(23, 0) if is_venue else time(11, 0),
            house_rules="No smoking indoors. Quiet hours 22:00–07:00." if not is_venue else "Music must end by 23:00. Outside caterers by arrangement.",
        )
        prop.amenities.set(self.amen(p["amenities"], "property"))
        self.attach(PropertyImage, {"property": prop}, p["images"])
        today = timezone.localdate()
        for i, r in enumerate(p["rooms"]):
            room = RoomType.objects.create(
                property=prop, name=r["name"], category=r["category"], bed_type=r["bed"], bed_count=r["beds"], max_adults=r["adults"],
                max_children=r["children"], base_price=Decimal(r["price"]), weekend_price=Decimal(r["weekend"]) if r["weekend"] else None,
                quantity=r["qty"], size_sqm=r["size"], sort_order=i,
                description=f"{r['name']} with {r['beds']} {r['bed']} bed{'s' if r['beds'] > 1 else ''}, about {r['size']} m².",
            )
            room.amenities.set(self.amen(r["amen"], "room"))
            self.attach(RoomImage, {"room_type": room}, r["images"])
            for name, start, end, price in p.get("seasonal", []):
                SeasonalRate.objects.create(room_type=room, name=name, start_date=today + timedelta(days=start),
                                            end_date=today + timedelta(days=end), nightly_price=Decimal(price) * Decimal(r["price"]) / Decimal(p["rooms"][0]["price"]))
        for v in p["venues"]:
            venue = Venue.objects.create(
                property=prop, name=v["name"], setting=v["setting"], capacity_seated=v["seated"], capacity_standing=v["standing"],
                area_sqm=v["area"], hourly_price=v["hourly"], half_day_price=v["half"], full_day_price=v["full"], event_price=v["event"],
                min_hours=2, opening_time=time(8, 0), closing_time=time(23, 0), turnover_minutes=60,
                description=f"{v['name']}: {v['seated']} seated or {v['standing']} standing, {v['area']} m².",
            )
            venue.amenities.set(self.amen(v["amen"], "venue"))
            self.attach(VenueImage, {"venue": venue}, v["images"])
            for name, desc, price, unit in v["packages"]:
                VenuePackage.objects.create(venue=venue, name=name, description=desc, price=Decimal(price), unit=unit)
            for name, price, unit in v["extras"]:
                VenueExtra.objects.create(venue=venue, name=name, price=Decimal(price), unit=unit)
        prop.refresh_starting_price()
        return prop

    def make_pending_vendor(self):
        owner = self.user("patrick@akagera.example", "Patrick", "Mugabo", "+250788222333", Role.VENDOR_OWNER)
        vendor = Vendor.objects.create(
            owner=owner, business_name="Akagera Safari Camp", legal_name="Akagera Safari Camp Ltd", tin="112998877",
            email="patrick@akagera.example", phone="+250788222333", address="Kayonza", city="Kayonza",
            status=Vendor.Status.PENDING, submitted_at=timezone.now() - timedelta(hours=5), payout_momo_number="+250788222333",
        )
        prop = Property.objects.create(
            vendor=vendor, name="Akagera Savannah Tents", category="lodge", city="Kayonza", district="Kayonza",
            address="Near Akagera National Park south gate", latitude=Decimal("-1.876700"), longitude=Decimal("30.711900"),
            tagline="Luxury tents with the sound of the savannah", status=Property.Status.PENDING,
            description="Eight safari tents with private decks overlooking the plains, minutes from the Akagera south gate.",
        )
        self.attach(PropertyImage, {"property": prop}, ["34", "00"])
        RoomType.objects.create(property=prop, name="Safari Tent", base_price=Decimal("150000"), quantity=8, max_adults=2)

    def pay(self, booking, option="full"):
        payment = pay.start_payment(booking, option=option, provider_code="sandbox", customer=booking.customer, base_url=settings.SITE_URL)
        txn = SandboxTransaction.objects.get(tx_ref=payment.reference)
        txn.status = SandboxTransaction.Status.SUCCESSFUL
        txn.method = "mobilemoneyrw"
        txn.save(update_fields=["status", "method"])
        return pay.verify_payment(payment)

    def guest(self, user):
        return bs.GuestDetails(user.get_full_name(), user.email, user.phone, "")

    def room_booking(self, customer, room, start_in, nights, rooms=1, adults=2, option="full", pay_now=True, pay_later=False):
        today = timezone.localdate()
        b = bs.create_room_booking(
            customer=customer, room_type_id=room.pk, check_in=today + timedelta(days=start_in),
            check_out=today + timedelta(days=start_in + nights), rooms=rooms, adults=adults, children=0,
            guest=self.guest(customer), pay_later=pay_later,
        )
        if pay_now:
            self.pay(b, option)
        return Booking.objects.get(pk=b.pk)

    def venue_booking(self, customer, venue, day_in, mode, guests, package=None, option="full", pay_now=True):
        b = bs.create_venue_booking(
            customer=customer, venue_id=venue.pk, day=timezone.localdate() + timedelta(days=day_in), mode=mode,
            start_time=time(10, 0) if mode == "hourly" else None, hours=4 if mode == "hourly" else None, guests=guests,
            package_id=package.pk if package else None, extras={}, event_type="Wedding reception" if guests > 100 else "Workshop",
            guest=self.guest(customer),
        )
        if pay_now:
            self.pay(b, option)
        return Booking.objects.get(pk=b.pk)

    def make_past(self, booking, days_ago, review=None):
        """Move a paid booking into the past, complete it and optionally add an approved review."""
        delta = timedelta(days=days_ago)
        if booking.kind == Booking.Kind.ROOM:
            nights = booking.nights
            check_in = timezone.localdate() - delta
            Booking.objects.filter(pk=booking.pk).update(check_in=check_in, check_out=check_in + timedelta(days=nights))
        else:
            length = booking.end_at - booking.start_at
            start = timezone.localtime(timezone.now() - delta).replace(hour=10, minute=0, second=0, microsecond=0)
            Booking.objects.filter(pk=booking.pk).update(start_at=start, end_at=start + length)
        shift = timezone.now() - delta - timedelta(days=7)
        Booking.objects.filter(pk=booking.pk).update(created_at=shift)
        booking.payments.update(verified_at=shift + timedelta(minutes=5), created_at=shift)
        booking.refresh_from_db()
        if booking.balance_due > 0:
            pay.record_offline_payment(booking, booking.balance_due, "cash", booking.vendor.owner, "Balance paid at check-in")
            booking.refresh_from_db()
        bs.complete_booking(booking)
        if review:
            rating, title, body = review
            r = Review.objects.create(booking=booking, property=booking.property, author=booking.customer, rating=rating,
                                      cleanliness=rating, service=rating, location=5, value=max(rating - 1, 3), title=title, body=body,
                                      status=Review.Status.APPROVED)
            refresh_property_rating(booking.property)
            return r
        return None

    def make_bookings(self):
        g, kevin, aline, sam = self.customers
        hills = Property.objects.get(name="Kigali Hills Hotel")
        kivu = Property.objects.get(name="Kivu Sands Resort")
        volcano = Property.objects.get(name="Volcano View Guesthouse")
        rebero = Property.objects.get(name="Rebero Garden Venue")
        hub = Property.objects.get(name="Kigali Business Hub")
        apartments = Property.objects.get(name="Gisenyi Lakeside Apartments")
        deluxe = hills.room_types.get(name="Deluxe King")
        suite = hills.room_types.get(name="Executive Suite")
        lake_room = kivu.room_types.get(name="Lake View Room")
        villa = kivu.room_types.get(name="Beach Villa with Plunge Pool")
        garden_double = volcano.room_types.get(name="Garden Double")
        apt = apartments.room_types.first()
        garden = rebero.venues.get(name="Main Garden & Gazebo")
        boardroom = hub.venues.get(name="Boardroom 1")
        conf = hills.venues.first()

        # Completed stays with reviews (past revenue in reports and wallets).
        self.make_past(self.room_booking(g, deluxe, 3, 2), 20, REVIEWS[0])
        self.make_past(self.room_booking(kevin, lake_room, 4, 3), 14, REVIEWS[4])
        self.make_past(self.room_booking(aline, garden_double, 5, 2, option="deposit"), 25)
        self.make_past(self.room_booking(sam, villa, 6, 2), 9, REVIEWS[1])
        self.make_past(self.room_booking(g, garden_double, 7, 3), 40, REVIEWS[3])
        self.make_past(self.venue_booking(aline, garden, 30, "event", 220, garden.packages.first(), option="deposit"), 30, REVIEWS[2])
        self.make_past(self.room_booking(kevin, apt, 8, 4), 6)

        # Upcoming confirmed bookings.
        self.room_booking(g, suite, 12, 2, option="deposit")
        self.room_booking(kevin, deluxe, 1, 3)
        self.room_booking(sam, lake_room, 21, 4, rooms=2, adults=4)
        self.venue_booking(kevin, boardroom, 3, "hourly", 10)
        self.venue_booking(sam, conf, 18, "full_day", 80, conf.packages.first(), option="deposit")
        self.venue_booking(g, garden, 60, "event", 300, garden.packages.first(), option="deposit")

        # Pending: one live hold awaiting payment, one pay-at-property request.
        self.room_booking(aline, deluxe, 9, 2, pay_now=False)
        self.room_booking(aline, garden_double, 15, 2, pay_now=False, pay_later=True)

        # A guest cancellation with a refund waiting for admin approval.
        b = self.room_booking(sam, apt, 30, 3)
        bs.cancel_booking(b, sam, "Flight changed")

        # A payout request for the admin queue.
        vendor = Vendor.objects.get(business_name="Lake Kivu Escapes")
        available = pay.available_balance(vendor)
        if available > 100000:
            pay.request_payout(vendor, (available / 2).quantize(Decimal("1")), vendor.owner)

    def make_coupons(self):
        today = timezone.localdate()
        Coupon.objects.get_or_create(code="KARIBU10", defaults={"description": "10% off your first Heza booking", "percent_off": Decimal("10"),
                                                                 "valid_until": today + timedelta(days=180), "max_uses": 500})
        ikaze = Vendor.objects.get(business_name="Ikaze Hospitality Group")
        Coupon.objects.get_or_create(code="IKAZE5000", defaults={"vendor": ikaze, "description": "RWF 5,000 off stays of 2+ nights",
                                                                  "amount_off": Decimal("5000"), "min_subtotal": Decimal("150000")})
        imena = Vendor.objects.get(business_name="Imena Events & Venues")
        Coupon.objects.get_or_create(code="WEDDING15", defaults={"vendor": imena, "description": "15% off weekday weddings", "percent_off": Decimal("15")})

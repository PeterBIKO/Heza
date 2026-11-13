# Heza

Heza is a multi-vendor marketplace for booking hotels, lodges, resorts, guesthouses, apartments and event
venues in Rwanda. Guests search verified listings, compare them, and book rooms or venue slots. They pay in
RWF by card or mobile money. Property owners run their business from a vendor dashboard, and the Heza team
verifies vendors and listings, moderates reviews, approves payouts and watches the money from an admin panel.

Built with Django 5, Django REST Framework, PostgreSQL, Bootstrap 5 and vanilla JavaScript. Maps use Leaflet
with OpenStreetMap.

## What's inside

* **Guest site**
  * Search by place, dates, guests, type, price, stars and amenities.
  * Map view, favorites, side-by-side compare, contact the property.
  * Booking with a live price quote, and payments through a gateway with signed webhooks.
  * Booking changes and cancellation with automatic refunds.
  * Reviews, written only after a completed stay.
* **Vendor dashboard**
  * Onboarding with KYC documents.
  * Properties of 10 types, with rooms, seasonal rates and photos.
  * Venues with hourly, half-day, full-day and event modes, plus packages and extras.
  * Availability calendar with blocks, bookings and check-in.
  * Pay-at-property approvals and cash/MoMo collection.
  * Coupons, reviews and replies, guest inquiries.
  * Wallet, ledger and payout requests, reports with CSV export.
  * Staff invites with roles (manager, receptionist).
* **Admin panel**
  * Vendor and document approval, property verification, user suspension.
  * Booking and payment search, with webhook logs and re-verification.
  * Refunds and payouts, review moderation, platform coupons, amenities.
  * Commission and tax settings, platform reports, and the audit log.
* **Money**: every booking has a double-entry ledger. Vendor credit, Heza commission, refunds, offline
  collections and payouts are all recorded in RWF. Commission is 10% by default, and can be overridden per
  vendor or per category.

## Run locally

Requirements: Python 3.12 and PostgreSQL 14 or newer. Docker is optional.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # then set SECRET_KEY to any long random string
createdb heza                   # or: docker compose up -d db redis
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py runserver 0.0.0.0:8742
```

Open http://localhost:8742.

Or run everything in containers (Postgres, Redis, app and scheduler, with demo data):

```bash
docker compose up --build
```

### Demo accounts

All demo accounts use the password `HezaDemo!2026`.

| Role | Email |
| --- | --- |
| Super admin | admin@heza.example |
| Vendor owner (Ikaze Hotels) | amani@ikaze.example |
| Vendor owner (Imena Events) | diane@imena.example |
| Receptionist (Ikaze) | reception@ikaze.example |
| Guest | guest@heza.example |

Payments in development go through the built-in **sandbox gateway**. You approve or decline on a TEST MODE
checkout page, and it sends an HMAC-signed webhook. The booking confirms only after the server verifies the
transaction. Flutterwave test keys can be added in `.env`. See [docs/setup.md](docs/setup.md).

## Tests

```bash
.venv/bin/python manage.py test
.venv/bin/ruff check apps heza
```

The suite covers availability and double-booking (including a concurrent race on PostgreSQL), venue slots
and turnover, pricing, tax, deposits, coupons and commission, and signed-webhook verification (tampered,
replayed, forged and duplicate webhooks). It also covers ledger and payouts, RBAC and vendor isolation,
account flows, reviews, and a full browser-style book-pay-confirm flow.

## Documentation

* [Setup and configuration](docs/setup.md)
* [User guide](docs/user-guide.md) for guests, vendors, staff and admins
* [Deployment](docs/deployment.md) on a VPS (Nginx + Gunicorn + HTTPS, or Docker Compose)
* [Backup and restore](docs/backup.md)
* [Architecture](docs/architecture.md), [database](docs/database.md), [UI/UX](docs/ui-ux.md)

# Heza — UI/UX direction

## Visual direction

"Quiet luxury, East-African warmth." Large, honest photography; generous whitespace; serif
display headings over a clean sans body; a restrained palette drawn from volcanic soil, tea
fields and lake light.

| Token | Value | Use |
|---|---|---|
| `--hz-ink` | `#14201c` | Text, dark surfaces |
| `--hz-forest` | `#1f4d3f` | Primary actions, links |
| `--hz-forest-600` | `#2b6a57` | Hover |
| `--hz-gold` | `#c8963e` | Accents, ratings, highlights |
| `--hz-sand` | `#f6f1e8` | Section backgrounds |
| `--hz-clay` | `#b4573a` | Alerts, urgency (hold timer) |
| Display font | Fraunces (fallback Georgia) | h1–h3, prices on detail pages |
| Body font | Inter (fallback system-ui) | Everything else |

Radius 14px on cards, 999px on pills; soft shadows only on hover/elevated elements.
Bootstrap 5 is themed through CSS variables in `static/css/heza.css` — no second component library.

## Page inventory

**Customer site**
- Home: full-bleed hero with search (destination, check-in/out, guests, category), category
  rail, featured stays, venues for events, destinations, trust/how-it-works, partner CTA.
- Search results: sticky filter sidebar (offcanvas on mobile) — category, price range, guests,
  stars, rating, amenities, sort; result cards; Leaflet map toggle.
- Property detail: photo mosaic, highlights, description, amenities, room cards with live
  availability for chosen dates, venues with packages, policies, map, reviews, contact form,
  favourite & compare buttons, sticky booking summary.
- Booking: room/venue booking form with live quote (JSON API), guest details, promo code,
  pay-at-property request where allowed.
- Booking detail: status timeline, hold countdown, price breakdown, payment options
  (deposit / full / balance), cancel (with refund preview), modify, review.
- Account: my bookings, favourites, compare, notifications, profile, password.
- Static: about, help/FAQ, terms, privacy, list-your-property.

**Partner portal** (`/dashboard/`) — left sidebar on desktop, offcanvas on mobile.
Overview KPIs, properties (+ gallery, rooms, seasonal rates, blocks, venues, packages, extras),
availability calendar, bookings (filters, detail, actions), payments at desk, wallet & ledger,
payouts, reviews, inquiries, coupons, staff & invites, documents & onboarding, reports, settings.

**Super admin** (`/admin-panel/`) — same shell, darker sidebar.
Overview, vendors (KYC review), properties (verification, featuring), users (suspend),
bookings, payments, webhooks log, refunds, payouts, reviews moderation, coupons, amenities,
reports, settings & category commissions, audit log.

## Component patterns

- **Listing card**: 4:3 image, category pill, favourite heart, name, city, rating chip,
  "from RWF x / night".
- **Status badges**: one colour per state (pending = amber, confirmed = forest, cancelled =
  clay, completed = slate, refunded = violet, expired = grey).
- **Data tables**: `table-responsive`, sticky header, right-aligned money, row actions in a
  dropdown; on small screens they scroll horizontally.
- **KPI tiles**: label, big number, delta/secondary line.
- **Forms**: rendered through one partial (`partials/form_fields.html`) so labels, help text
  and errors look identical everywhere.
- **Empty states**: icon, one sentence explaining why it's empty, one primary action.
- **Loading**: buttons get a spinner and disable on submit; JSON-driven panels show skeletons.
- **Errors**: Bootstrap alerts from Django messages; field errors inline; custom 403/404/429/500.

## Accessibility & responsiveness

Mobile-first; tested at 360px, 768px and 1280px. Colour contrast ≥ 4.5:1 for text, visible
focus rings, labels on all inputs, `aria-live` on the quote panel and hold timer, alt text on
listing photos, keyboard-operable gallery and calendars.

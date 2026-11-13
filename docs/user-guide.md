# Heza user guide

Heza has three areas:

* the public site, for guests;
* the **vendor dashboard** at `/dashboard/`, for property owners and their staff;
* the **admin panel** at `/admin-panel/`, for the Heza team.

All amounts are in Rwandan francs (RWF).

## Guests

### Find a place

* Search from the home page by destination, dates and number of guests. Destinations can be a city or a
  district.
* On the results page you can:
  * filter by property type, price range, star rating, guest rating and amenities;
  * sort by recommended, price or rating;
  * switch to the map view.
* With dates selected, Heza only shows places that actually have availability for those dates.
* The heart icon saves a place to **Favorites**. **Compare** puts up to four places side by side.
* A property page shows photos, rooms or venues, amenities, house rules, the cancellation policy, the location
  on the map, and verified reviews. **Contact property** sends a question straight to the vendor.

### Book a room

1. Choose a room and enter dates, rooms and guests. The price panel updates as you type. It shows:
   * nightly rates, including seasonal prices;
   * taxes, and any coupon;
   * the amount due now.
2. Enter the guest details and confirm. The booking is created as **Pending**, and the rooms are held for
   30 minutes while you pay. A countdown on the booking page shows the time left.
3. Pick how to pay. The options depend on the property:
   * **Pay in full** by card or mobile money;
   * **Pay a deposit** now and the balance later;
   * **Request to pay at the property**. The vendor must approve the request, and your dates stay held while
     they decide.
4. You pay on the payment provider's secure page. Heza never sees your card number.
5. The booking becomes **Confirmed** only after Heza has verified the payment with the provider. You receive
   an email, an SMS and an in-app notification.

### Book a venue

1. Pick a date and a mode:
   * **Hourly**, with a start and end time;
   * **Half day**, morning or afternoon;
   * **Full day**;
   * **Event**.
2. Times that are already taken, including the vendor's cleaning buffer between events, are greyed out.
3. Add a package (for example a wedding package) and extras (sound system, decoration, catering per guest).
   The total updates live.

### Manage a booking

All your bookings are under **My bookings**.

* **Modify**: change dates, rooms or guests, if the property allows it. Heza re-prices the booking and checks
  availability. If the new total is higher, the difference becomes the balance due. If it is lower, the
  excess is refunded.
* **Cancel**: before you confirm, the page shows the exact refund under the property's policy:

  | Policy | Refund |
  | --- | --- |
  | Flexible | Full refund up to 24 hours before arrival |
  | Moderate | Full refund up to 5 days before, 50% after |
  | Strict | 50% refund up to 7 days before, none after |
  | Non-refundable | No refund |

  Refunds are sent back through the original payment method.
* **Review**: after a completed stay or event, you can leave one review per booking. The Heza team checks
  reviews before they appear.

### Your account

* **Profile** holds your name, phone and marketing preference. You can also change your password there, and
  use **Forgot password** on the login page.
* You must verify your email before booking. Use *Resend* on the verification page if the email didn't
  arrive.

## Vendors (property owners)

### Get approved

1. Go to **List your property** and choose *Become a partner*. This creates your owner account and business
   profile.
2. In **Onboarding**:
   * fill in the business details (legal name, TIN, address) and payout details (MoMo number or bank account);
   * upload documents: an RDB registration certificate, a TIN certificate, the owner's national ID or
     passport, and an RDB tourism operating licence where it applies. Files can be PDF, JPG or PNG, up to 8 MB. They are stored privately and only you and the Heza
     team can open them.
3. Click **Submit for review**. The Heza team approves your business, or asks for changes with a note. You are
   notified either way.

### Create listings

1. In **Properties**, choose **Add property**. Pick one of the 10 types:
   * lodging: hotel, lodge, resort, guesthouse, apartment;
   * venues: wedding venue, conference centre, meeting room, garden, event hall.
2. Fill in the address and drag the map pin to the exact location. Then set amenities, check-in and
   check-out times, house rules and the cancellation policy.
3. Choose the payment mode: **full payment** or **deposit** (you set the percentage). Optionally allow
   **pay at property** requests.
4. Upload photos and choose a cover image.
5. Add rooms or venues:
   * **Rooms**: name, capacity, beds, size, number of units, base price per night, weekend price, minimum
     nights and amenities. Under **Seasonal rates**, set a different nightly price for date ranges such as
     the high season or Christmas.
   * **Venues**: seated and standing capacity, and the price for each mode. Also set opening hours, the
     turnover buffer between events, and the minimum hours for hourly bookings. Then add **packages**
     (a fixed price, or a price per guest) and **extras** (a fixed price, or a price per guest or per hour).
6. Click **Submit for verification**. The listing goes public only once the Heza team has verified both your
   business and the property.

### Day-to-day operations

* **Calendar**: a month view per room type or venue. It shows booked units, holds and blocks. To block dates
  for maintenance or private use, open the room or venue and add a block under **Blocks**. Remove the block
  there to unblock the dates.
* **Bookings**: filter by status, property or dates, and export to CSV. Open a booking to:
  * approve or decline a pay-at-property request;
  * record a payment collected at the property (cash, POS, MoMo). Heza's commission on it is deducted from
    your wallet;
  * check the guest in, or mark the booking completed;
  * cancel, as the vendor. The guest gets a full refund of what they paid.
* **Inquiries**: reply to guest questions sent from your property pages.
* **Reviews**: reply publicly to approved reviews.
* **Coupons**: create percentage or fixed discounts, limited to your properties. You can set dates, a
  minimum spend and a usage limit.

### Money

* **Wallet** shows:
  * your balance, the amount reserved for payout requests, and what is available;
  * the full ledger: every credit, commission deduction, refund and payout.
* For each online payment you receive the amount minus Heza's commission. The commission is 10% by default;
  Heza may agree a different rate for your business or category.
* **Request payout** sends funds from your available balance to your MoMo or bank account. The Heza team
  approves the request and marks it paid with a transfer reference.
* **Reports**: revenue, bookings, occupancy and top properties for any date range, with CSV export.

### Staff

Under **Staff**, invite people by email. They accept the invite link and set a password.

| Role | Can do |
| --- | --- |
| Owner | Everything, including the wallet, payouts, staff and business settings |
| Property manager | Listings, rooms and venues, calendar, bookings, coupons, reviews, inquiries and reports, for the properties you assign them |
| Receptionist | Bookings, check-in, collect payments at the property, view the calendar, reply to inquiries |

## Heza administrators

Sign in with a super-admin account and open **Admin panel**.

* **Overview**: what needs attention, such as:
  * pending vendors, properties, reviews, refunds and payouts;
  * failed webhooks;
  * platform GMV and commission.
* **Vendors**:
  * open the KYC documents, and accept or reject each one;
  * approve, reject (with a note), suspend or reinstate a vendor;
  * set a commission override for that vendor.
* **Properties**: review the details and photos, then verify, reject or suspend. Suspended listings vanish
  from search at once.
* **Users**: search, then suspend or reinstate. A suspended user is signed out on their next request and
  cannot sign in.
* **Bookings and Payments**: search by reference, email or provider reference. **Re-verify** asks the gateway
  for the current status of a payment. **Webhooks** lists every incoming event, with its signature result
  and processing outcome.
* **Refunds**: refunds created by cancellations wait here. **Process** sends them to the gateway; **Reject**
  requires a note.
* **Payouts**: approve or reject vendor requests, then **Mark paid** with the bank or MoMo transfer
  reference. This debits the vendor's wallet.
* **Reviews**: approve or reject (hide) guest reviews. Ratings count approved reviews only.
* **Coupons**: platform-wide promotions. **Amenities**: the amenity list vendors choose from.
* **Settings**:
  * default commission and per-category overrides;
  * the tax rate, and whether prices include tax;
  * the minimum payout and the support contacts.
* **Reports**: platform-wide revenue, commission, bookings by type and city, and top vendors, with CSV
  export.
* **Audit log**: every sensitive action (approvals, suspensions, refunds, payouts, settings changes), with
  who did it, when, and from which IP.

The low-level Django admin at `/django-admin/` is for data fixes by engineers. Payment and audit records
there are read-only.

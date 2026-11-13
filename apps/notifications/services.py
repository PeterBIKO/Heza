import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .backends import get_sms_backend, get_whatsapp_backend
from .models import Notification

log = logging.getLogger(__name__)


def absolute(path):
    if path.startswith("http"):
        return path
    return settings.SITE_URL + path


def send_email(to, subject, lines, *, user=None, event="generic", cta_url="", cta_label="", greeting=""):
    context = {"subject": subject, "lines": lines, "cta_url": absolute(cta_url) if cta_url else "", "cta_label": cta_label,
               "greeting": greeting or (_("Hello %(n)s,") % {"n": user.display_name} if user else _("Hello,"))}
    text = render_to_string("emails/notification.txt", context)
    html = render_to_string("emails/notification.html", context)
    status, error = Notification.Status.SENT, ""
    try:
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [to])
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception as exc:  # noqa: BLE001 - a mail outage must not break bookings
        log.exception("email to %s failed", to)
        status, error = Notification.Status.FAILED, str(exc)[:255]
    return Notification.objects.create(user=user, recipient=to, channel="email", event=event, subject=subject[:200],
                                       body=text, link=cta_url, status=status, error=error)


def send_sms(to, body, *, user=None, event="generic"):
    if not to:
        return None
    status, error = Notification.Status.SENT, ""
    try:
        get_sms_backend().send(to, body)
    except Exception as exc:  # noqa: BLE001
        status, error = Notification.Status.FAILED, str(exc)[:255]
    return Notification.objects.create(user=user, recipient=to, channel="sms", event=event, body=body, status=status, error=error)


def send_whatsapp(to, body, *, user=None, event="generic"):
    if not to:
        return None
    status, error = Notification.Status.SENT, ""
    try:
        get_whatsapp_backend().send(to, body)
    except Exception as exc:  # noqa: BLE001
        status, error = Notification.Status.FAILED, str(exc)[:255]
    return Notification.objects.create(user=user, recipient=to, channel="whatsapp", event=event, body=body, status=status, error=error)


def in_app(user, event, subject, body="", link=""):
    if user is None:
        return None
    return Notification.objects.create(user=user, recipient=user.email, channel="in_app", event=event, subject=subject[:200], body=body, link=link)


def vendor_recipients(vendor, property_obj=None):
    users = {vendor.owner}
    for m in vendor.memberships.filter(is_active=True).select_related("user").prefetch_related("properties"):
        props = list(m.properties.all())
        if property_obj is None or not props or property_obj in props:
            users.add(m.user)
    return [u for u in users if u.is_active and not u.is_suspended]


def notify_vendor(vendor, event, subject, body="", link="", email=True):
    link = link or reverse("dashboard:overview")
    for user in vendor_recipients(vendor):
        in_app(user, event, subject, body, link)
    if email:
        send_email(vendor.email, subject, [body] if body else [], user=vendor.owner, event=event, cta_url=link, cta_label=_("Open dashboard"))


def notify_admins(event, subject, link="", body=""):
    User = get_user_model()
    for admin in User.objects.filter(role="super_admin", is_active=True):
        in_app(admin, event, subject, body, link)


def _when(b):
    if b.kind == "room":
        return _("%(ci)s → %(co)s · %(n)s night(s)") % {"ci": b.check_in.strftime("%a %d %b %Y"), "co": b.check_out.strftime("%a %d %b %Y"), "n": b.nights}
    start = timezone.localtime(b.start_at)
    return _("%(d)s, %(s)s–%(e)s") % {"d": start.strftime("%a %d %b %Y"), "s": start.strftime("%H:%M"), "e": timezone.localtime(b.end_at).strftime("%H:%M")}


def _money(amount, cur):
    return f"{amount:,.0f} {cur}"


def notify_booking(event, booking, payment=None, refund=None):
    """Fan out booking lifecycle messages. Failures are recorded, never raised."""
    try:
        _notify_booking(event, booking, payment, refund)
    except Exception:  # noqa: BLE001
        log.exception("notification %s for %s failed", event, booking)


def _notify_booking(event, b, payment, refund):
    customer = b.customer
    link = reverse("bookings:detail", args=[b.reference])
    vlink = reverse("dashboard:booking_detail", args=[b.reference])
    what = f"{b.listing_name} at {b.property.name}"
    when = _when(b)
    total = _money(b.total, b.currency)

    def to_guest(subject, lines, sms=None, cta=None):
        send_email(b.guest_email, subject, lines, user=customer, event=event, cta_url=link, cta_label=cta or _("View booking"))
        in_app(customer, event, subject, " ".join(lines[:1]), link)
        if sms:
            send_sms(b.guest_phone, sms, user=customer, event=event)
            send_whatsapp(b.guest_phone, sms, user=customer, event=event)

    def to_vendor(subject, lines, sms=None):
        for user in vendor_recipients(b.vendor, b.property):
            in_app(user, event, subject, " ".join(lines[:1]), vlink)
        send_email(b.property.email or b.vendor.email, subject, lines, user=b.vendor.owner, event=event, cta_url=vlink, cta_label=_("Open booking"))
        if sms:
            send_sms(b.property.phone or b.vendor.phone, sms, event=event)

    if event == "booking_created":
        if b.pay_later_requested:
            to_guest(_("Request received · %(ref)s") % {"ref": b.reference},
                     [_("Your pay-at-property request for %(w)s is with the property for approval.") % {"w": what}, when, _("Total: %(t)s") % {"t": total}])
        else:
            to_guest(_("Complete your booking · %(ref)s") % {"ref": b.reference},
                     [_("We're holding %(w)s for you for %(m)s minutes.") % {"w": what, "m": settings.BOOKING_HOLD_MINUTES}, when,
                      _("Amount due now: %(a)s (total %(t)s)") % {"a": _money(b.deposit_amount, b.currency), "t": total}],
                     cta=_("Pay now"))
    elif event == "vendor_pay_later_request":
        to_vendor(_("Pay-at-property request · %(ref)s") % {"ref": b.reference},
                  [_("%(g)s asked to pay at the property for %(w)s.") % {"g": b.guest_name, "w": what}, when, _("Approve or decline it in your dashboard.")])
    elif event == "booking_confirmed":
        to_guest(_("Booking confirmed · %(ref)s") % {"ref": b.reference},
                 [_("You're all set for %(w)s.") % {"w": what}, when, _("Paid: %(p)s of %(t)s") % {"p": _money(b.amount_paid, b.currency), "t": total},
                  _("Address: %(a)s, %(c)s") % {"a": b.property.address, "c": b.property.city}],
                 sms=_("Heza: booking %(ref)s confirmed at %(p)s, %(w)s.") % {"ref": b.reference, "p": b.property.name, "w": when})
    elif event == "vendor_new_booking":
        to_vendor(_("New booking · %(ref)s") % {"ref": b.reference},
                  [_("%(g)s booked %(w)s.") % {"g": b.guest_name, "w": what}, when, _("Paid %(p)s of %(t)s") % {"p": _money(b.amount_paid, b.currency), "t": total}],
                  sms=_("Heza: new booking %(ref)s for %(w)s, %(when)s.") % {"ref": b.reference, "w": b.listing_name, "when": when})
    elif event == "payment_received":
        to_guest(_("Payment received · %(ref)s") % {"ref": b.reference},
                 [_("We received %(a)s via %(p)s (ref %(r)s).") % {"a": _money(payment.amount, payment.currency), "p": payment.provider, "r": payment.reference},
                  _("Balance remaining: %(b)s") % {"b": _money(b.balance_due, b.currency)}])
        for user in vendor_recipients(b.vendor, b.property):
            in_app(user, event, _("Payment received for %(ref)s: %(a)s") % {"ref": b.reference, "a": _money(payment.amount, payment.currency)}, "", vlink)
    elif event == "payment_failed":
        to_guest(_("Payment not completed · %(ref)s") % {"ref": b.reference},
                 [_("Your payment of %(a)s did not go through.") % {"a": _money(payment.amount, payment.currency)},
                  _("You can try again while your booking is held.")], cta=_("Try again"))
    elif event == "booking_cancelled":
        to_guest(_("Booking cancelled · %(ref)s") % {"ref": b.reference},
                 [_("Your booking for %(w)s has been cancelled.") % {"w": what}, when,
                  _("Any refund due will be sent to your original payment method once approved.")],
                 sms=_("Heza: booking %(ref)s has been cancelled.") % {"ref": b.reference})
    elif event == "vendor_booking_cancelled":
        to_vendor(_("Booking cancelled · %(ref)s") % {"ref": b.reference}, [_("%(w)s is free again for %(when)s.") % {"w": b.listing_name, "when": when}])
    elif event == "booking_modified":
        to_guest(_("Booking updated · %(ref)s") % {"ref": b.reference},
                 [_("Your booking now reads: %(when)s.") % {"when": when}, _("New total: %(t)s. Balance due: %(d)s") % {"t": total, "d": _money(b.balance_due, b.currency)}])
        for user in vendor_recipients(b.vendor, b.property):
            in_app(user, event, _("Booking %(ref)s was modified") % {"ref": b.reference}, when, vlink)
    elif event == "refund_processed":
        to_guest(_("Refund sent · %(ref)s") % {"ref": b.reference},
                 [_("%(a)s has been refunded to your original payment method.") % {"a": _money(refund.amount, refund.currency)},
                  _("Banks and mobile money operators can take a few days to show it.")])
    elif event == "pay_later_declined":
        to_guest(_("Please pay online · %(ref)s") % {"ref": b.reference},
                 [_("The property could not approve paying on arrival. Your dates are held for %(m)s more minutes if you pay online.") % {"m": settings.BOOKING_HOLD_MINUTES}],
                 cta=_("Pay now"))
    elif event == "review_invite":
        to_guest(_("How was %(p)s?") % {"p": b.property.name},
                 [_("Thanks for booking with Heza. Your verified review helps other travellers.")], cta=_("Write a review"))


def send_verification_email(user, request=None):
    from apps.accounts.tokens import make_email_token

    path = reverse("accounts:verify_email", args=[make_email_token(user)])
    send_email(user.email, _("Confirm your email for Heza"),
               [_("Confirm your email address to start booking and managing your account."), _("This link expires in 3 days.")],
               user=user, event="email_verification", cta_url=path, cta_label=_("Confirm email"))
    return path


def send_staff_invite(invite):
    send_email(invite.email, _("You're invited to join %(v)s on Heza") % {"v": invite.vendor.business_name},
               [_("%(v)s invited you as %(r)s.") % {"v": invite.vendor.business_name, "r": invite.get_role_display()},
                _("The invitation expires on %(d)s.") % {"d": invite.expires_at.strftime("%d %b %Y")}],
               event="staff_invite", cta_url=invite.get_accept_url(), cta_label=_("Accept invitation"))


def notify_inquiry(inquiry):
    prop = inquiry.property
    link = reverse("dashboard:inquiries")
    for user in vendor_recipients(prop.vendor, prop):
        in_app(user, "inquiry_received", _("New message about %(p)s") % {"p": prop.name}, inquiry.message[:200], link)
    send_email(prop.email or prop.vendor.email, _("New guest message · %(p)s") % {"p": prop.name},
               [_("From: %(n)s <%(e)s> %(ph)s") % {"n": inquiry.name, "e": inquiry.email, "ph": inquiry.phone}, inquiry.message],
               user=prop.vendor.owner, event="inquiry_received", cta_url=link, cta_label=_("Reply"))

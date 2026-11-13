"""Periodic housekeeping. Run every 5 minutes from cron or a systemd timer:

    */5 * * * * cd /srv/heza && .venv/bin/python manage.py heza_maintenance

- expires unpaid booking holds so inventory is released
- completes confirmed bookings whose stay/event has ended and invites guests to review
- re-verifies payments stuck in "pending" with the provider (missed webhooks)
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bookings.services import complete_finished_bookings, expire_stale_holds
from apps.payments.models import Payment
from apps.payments.services import verify_payment


class Command(BaseCommand):
    help = "Expire holds, complete finished bookings and reconcile pending payments."

    def handle(self, *args, **opts):
        expired = expire_stale_holds()
        completed = complete_finished_bookings()
        window = timezone.now() - timedelta(minutes=2)
        reconciled = 0
        for payment in Payment.objects.filter(status=Payment.Status.PENDING, created_at__lt=window,
                                              created_at__gt=timezone.now() - timedelta(days=2)).exclude(provider="offline")[:200]:
            before = payment.status
            if verify_payment(payment).status != before:
                reconciled += 1
        self.stdout.write(f"expired_holds={expired} completed={completed} payments_reconciled={reconciled}")

import logging
import uuid

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.ratelimit import ratelimit

from .models import Payment, SandboxTransaction
from .providers.sandbox import build_webhook_body, sign
from .services import handle_webhook, verify_payment

log = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 64 * 1024


@login_required
def payment_return(request, reference):
    """Where the gateway sends the guest back. Query-string status is ignored; we verify server-side."""
    payment = get_object_or_404(Payment.objects.select_related("booking__property"), reference=reference)
    if payment.booking.customer_id != request.user.pk and not request.user.is_platform_admin:
        raise Http404
    txn_hint = request.GET.get("transaction_id", "")[:40]
    payment = verify_payment(payment, txn_hint)
    payment.booking.refresh_from_db()
    return render(request, "payments/return.html", {"payment": payment, "b": payment.booking})


@csrf_exempt
@require_POST
@ratelimit("webhook", "300/m")
def webhook(request, provider):
    if len(request.body) > MAX_WEBHOOK_BYTES:
        return HttpResponse("payload too large", status=413)
    status, message = handle_webhook(provider, request.body, request.META)
    return HttpResponse(message, status=status, content_type="text/plain")


def _sandbox_enabled():
    return "sandbox" in settings.PAYMENT_PROVIDERS_ENABLED


def sandbox_checkout(request, txn_id):
    """Hosted page of the simulated gateway. It never writes to Heza's payment tables directly."""
    if not _sandbox_enabled():
        raise Http404
    txn = get_object_or_404(SandboxTransaction, txn_id=txn_id)
    payment = Payment.objects.filter(reference=txn.tx_ref).select_related("booking__property").first()
    if request.method == "POST" and txn.status == SandboxTransaction.Status.PENDING:
        action = request.POST.get("action")
        txn.method = request.POST.get("method", "card")[:20]
        txn.status = SandboxTransaction.Status.SUCCESSFUL if action == "approve" else SandboxTransaction.Status.FAILED
        txn.save(update_fields=["status", "method"])
        deliver_sandbox_webhook(txn, request)
        return HttpResponseRedirect(f"{txn.redirect_url}?tx_ref={txn.tx_ref}&status={txn.status}")
    if txn.status != SandboxTransaction.Status.PENDING:
        return HttpResponseRedirect(f"{txn.redirect_url}?tx_ref={txn.tx_ref}")
    return render(request, "payments/sandbox_checkout.html", {"txn": txn, "payment": payment})


def deliver_sandbox_webhook(txn, request=None):
    """Sign and deliver the gateway's webhook. SANDBOX_WEBHOOK_DELIVERY=http posts over the network
    (exercises the full HTTP path); the default dispatches in-process through the same handler."""
    body = build_webhook_body(txn, f"evt_{uuid.uuid4().hex[:20]}")
    signature = sign(body)
    mode = getattr(settings, "SANDBOX_WEBHOOK_DELIVERY", "inprocess")
    if mode == "http" and request is not None:
        url = request.build_absolute_uri(reverse("payments:webhook", args=["sandbox"]))
        try:
            requests.post(url, data=body, headers={"Content-Type": "application/json", "X-Heza-Sandbox-Signature": signature}, timeout=10)
            return
        except requests.RequestException:
            log.warning("sandbox webhook HTTP delivery failed; falling back to in-process")
    handle_webhook("sandbox", body, {"HTTP_X_HEZA_SANDBOX_SIGNATURE": signature})

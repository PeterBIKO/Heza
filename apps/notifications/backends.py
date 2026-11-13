"""SMS and WhatsApp backends. Select with SMS_BACKEND / WHATSAPP_BACKEND settings."""
import logging

import requests
from django.conf import settings
from django.utils.module_loading import import_string

log = logging.getLogger("heza.messaging")


class BaseBackend:
    channel = ""

    def send(self, to, body):
        raise NotImplementedError


class ConsoleSMSBackend(BaseBackend):
    channel = "sms"

    def send(self, to, body):
        log.info("[SMS → %s] %s", to, body)
        return "console"


class AfricasTalkingSMSBackend(BaseBackend):
    """https://developers.africastalking.com/docs/sms/sending — username 'sandbox' uses the sandbox API."""

    channel = "sms"

    def send(self, to, body):
        if not settings.AFRICASTALKING_API_KEY:
            raise RuntimeError("AFRICASTALKING_API_KEY is not set")
        sandbox = settings.AFRICASTALKING_USERNAME == "sandbox"
        url = "https://api.sandbox.africastalking.com/version1/messaging" if sandbox else "https://api.africastalking.com/version1/messaging"
        data = {"username": settings.AFRICASTALKING_USERNAME, "to": to, "message": body}
        if settings.AFRICASTALKING_SENDER_ID:
            data["from"] = settings.AFRICASTALKING_SENDER_ID
        resp = requests.post(url, data=data, headers={"apiKey": settings.AFRICASTALKING_API_KEY, "Accept": "application/json"}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("SMSMessageData", {}).get("Message", "sent")


class ConsoleWhatsAppBackend(BaseBackend):
    channel = "whatsapp"

    def send(self, to, body):
        log.info("[WhatsApp → %s] %s", to, body)
        return "console"


class WhatsAppCloudBackend(BaseBackend):
    """Placeholder for Meta WhatsApp Cloud API. Requires approved message templates; not enabled yet."""

    channel = "whatsapp"

    def send(self, to, body):
        raise NotImplementedError("WhatsApp Cloud API is not configured. Use ConsoleWhatsAppBackend.")


def get_sms_backend():
    return import_string(settings.SMS_BACKEND)()


def get_whatsapp_backend():
    return import_string(settings.WHATSAPP_BACKEND)()

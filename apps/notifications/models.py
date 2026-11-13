from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "in_app", _("In-app")
        EMAIL = "email", _("Email")
        SMS = "sms", _("SMS")
        WHATSAPP = "whatsapp", _("WhatsApp")

    class Status(models.TextChoices):
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    recipient = models.CharField(max_length=160, help_text=_("Email address or phone number"))
    channel = models.CharField(max_length=10, choices=Channel.choices)
    event = models.CharField(max_length=60, db_index=True)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    link = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    error = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel}:{self.event} → {self.recipient}"

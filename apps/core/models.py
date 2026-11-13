from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


PERCENT_VALIDATORS = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]


class PlatformSettings(models.Model):
    """Singleton row holding platform-wide business defaults editable by super admins."""

    commission_rate = models.DecimalField(
        _("default commission %"), max_digits=5, decimal_places=2, default=Decimal("10.00"), validators=PERCENT_VALIDATORS
    )
    tax_rate = models.DecimalField(
        _("tax (VAT) %"), max_digits=5, decimal_places=2, default=Decimal("18.00"), validators=PERCENT_VALIDATORS
    )
    tax_inclusive = models.BooleanField(
        _("prices include tax"), default=False, help_text=_("If off, tax is added on top of listed prices.")
    )
    min_payout_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("10000"))
    support_phone = models.CharField(max_length=30, default="+250 788 000 000")
    support_email = models.EmailField(default="support@heza.rw")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("platform settings")
        verbose_name_plural = _("platform settings")

    def __str__(self):
        return "Platform settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete("heza:platform_settings")

    @classmethod
    def load(cls):
        obj = cache.get("heza:platform_settings")
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set("heza:platform_settings", obj, 300)
        return obj


class CategoryCommission(models.Model):
    """Optional per-property-category commission override (vendor override still wins)."""

    category = models.CharField(max_length=40, unique=True)
    rate = models.DecimalField(max_digits=5, decimal_places=2, validators=PERCENT_VALIDATORS)

    def __str__(self):
        return f"{self.category}: {self.rate}%"


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"

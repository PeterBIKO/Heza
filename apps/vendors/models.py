import secrets
from datetime import timedelta

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import PERCENT_VALIDATORS, TimeStampedModel
from apps.core.validators import (
    RandomFilename,
    validate_document_upload,
    validate_image_upload,
)


def get_private_storage():
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


class Vendor(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending review")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        SUSPENDED = "suspended", _("Suspended")

    class PayoutMethod(models.TextChoices):
        MOMO = "momo", _("Mobile money")
        BANK = "bank", _("Bank transfer")

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_vendors")
    business_name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    legal_name = models.CharField(max_length=200, blank=True)
    tin = models.CharField(_("TIN"), max_length=30, blank=True, help_text=_("Rwanda Revenue Authority tax ID"))
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=80, default="Kigali")
    country = models.CharField(max_length=2, default="RW")
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to=RandomFilename("vendors/logos"), blank=True, validators=[validate_image_upload])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    commission_rate = models.DecimalField(
        _("commission override %"), max_digits=5, decimal_places=2, null=True, blank=True, validators=PERCENT_VALIDATORS,
        help_text=_("Leave empty to use the category or platform default."),
    )
    payout_method = models.CharField(max_length=10, choices=PayoutMethod.choices, default=PayoutMethod.MOMO)
    payout_momo_number = models.CharField(max_length=20, blank=True)
    payout_bank_name = models.CharField(max_length=80, blank=True)
    payout_account_name = models.CharField(max_length=120, blank=True)
    payout_account_number = models.CharField(max_length=40, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    review_note = models.TextField(blank=True)

    class Meta:
        ordering = ["business_name"]

    def __str__(self):
        return self.business_name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.business_name)[:160] or "vendor"
            slug, n = base, 2
            while Vendor.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED

    @property
    def payout_destination(self):
        if self.payout_method == self.PayoutMethod.MOMO:
            return f"MoMo {self.payout_momo_number}"
        return f"{self.payout_bank_name} · {self.payout_account_name} · {self.payout_account_number}"


class VendorDocument(TimeStampedModel):
    class DocType(models.TextChoices):
        RDB_CERTIFICATE = "rdb_certificate", _("RDB business registration certificate")
        TIN_CERTIFICATE = "tin_certificate", _("TIN certificate")
        TOURISM_LICENSE = "tourism_license", _("RDB tourism operating licence")
        OWNER_ID = "owner_id", _("Owner national ID / passport")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Rejected")

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=30, choices=DocType.choices)
    file = models.FileField(
        upload_to=RandomFilename("vendor_docs"), storage=get_private_storage, validators=[validate_document_upload]
    )
    original_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.vendor} · {self.get_doc_type_display()}"

    def get_absolute_url(self):
        return reverse("vendors:document_download", args=[self.pk])


class StaffMembership(TimeStampedModel):
    class StaffRole(models.TextChoices):
        PROPERTY_MANAGER = "property_manager", _("Property manager")
        RECEPTIONIST = "receptionist", _("Receptionist")

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=StaffRole.choices)
    properties = models.ManyToManyField("properties.Property", blank=True, related_name="staff_memberships")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("vendor", "user")]

    def __str__(self):
        return f"{self.user} @ {self.vendor} ({self.get_role_display()})"


def _invite_token():
    return secrets.token_urlsafe(32)


def _invite_expiry():
    return timezone.now() + timedelta(days=7)


class StaffInvite(TimeStampedModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=StaffMembership.StaffRole.choices)
    properties = models.ManyToManyField("properties.Property", blank=True, related_name="+")
    token = models.CharField(max_length=64, unique=True, default=_invite_token)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    expires_at = models.DateTimeField(default=_invite_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite {self.email} → {self.vendor}"

    @property
    def is_usable(self):
        return not self.revoked and self.accepted_at is None and self.expires_at > timezone.now()

    def get_accept_url(self):
        return reverse("vendors:accept_invite", args=[self.token])

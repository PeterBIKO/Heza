from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    SUPER_ADMIN = "super_admin", _("Super admin")
    VENDOR_OWNER = "vendor_owner", _("Vendor owner")
    PROPERTY_MANAGER = "property_manager", _("Property manager")
    RECEPTIONIST = "receptionist", _("Receptionist")
    CUSTOMER = "customer", _("Customer")


VENDOR_ROLES = {Role.VENDOR_OWNER, Role.PROPERTY_MANAGER, Role.RECEPTIONIST}


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, role=Role.SUPER_ADMIN, is_email_verified=True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    username = None
    email = models.EmailField(_("email address"), unique=True)
    phone = models.CharField(_("phone"), max_length=20, blank=True, db_index=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    is_email_verified = models.BooleanField(default=False)
    is_suspended = models.BooleanField(default=False)
    suspended_reason = models.CharField(max_length=255, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    marketing_opt_in = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.get_full_name() or self.email

    @property
    def display_name(self):
        return self.get_full_name() or self.email.split("@")[0]

    @property
    def is_platform_admin(self):
        return self.role == Role.SUPER_ADMIN or self.is_superuser

    @property
    def is_vendor_user(self):
        return self.role in VENDOR_ROLES

    @property
    def is_customer(self):
        return self.role == Role.CUSTOMER

    def suspend(self, reason=""):
        self.is_suspended = True
        self.suspended_reason = reason[:255]
        self.suspended_at = timezone.now()
        self.save(update_fields=["is_suspended", "suspended_reason", "suspended_at"])

    def reinstate(self):
        self.is_suspended = False
        self.suspended_reason = ""
        self.suspended_at = None
        self.save(update_fields=["is_suspended", "suspended_reason", "suspended_at"])

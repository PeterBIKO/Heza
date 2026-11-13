"""Heza settings. Every secret and environment-specific value comes from the environment (.env in dev)."""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", "0.0.0.0"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    USE_SQLITE=(bool, False),
    SECURE_SSL=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

DEBUG = env("DEBUG")
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")
if not DEBUG and SECRET_KEY == "dev-insecure-change-me":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set SECRET_KEY in the environment for non-debug deployments.")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
SITE_URL = env("SITE_URL", default="http://localhost:8742").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.vendors",
    "apps.properties",
    "apps.bookings",
    "apps.payments",
    "apps.reviews",
    "apps.notifications",
    "apps.reports",
    "apps.dashboard",
    "apps.adminpanel",
    "apps.api",
    "apps.public",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.accounts.middleware.SuspendedUserMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "heza.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "heza.wsgi.application"

if env("USE_SQLITE"):
    # Emergency fallback only. Row locking (select_for_update) is a no-op on SQLite.
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    DATABASES = {"default": env.db("DATABASE_URL", default="postgres://heza:heza@localhost:5432/heza")}
    DATABASES["default"]["ATOMIC_REQUESTS"] = False
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOrPhoneBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:after_login"
LOGOUT_REDIRECT_URL = "public:home"
PASSWORD_RESET_TIMEOUT = 60 * 60 * 3

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Africa/Kigali"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
# Vendor KYC documents never live under MEDIA_ROOT; they are streamed through a permission-checked view.
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media")))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
MAX_IMAGE_UPLOAD_MB = 5
MAX_DOCUMENT_UPLOAD_MB = 8

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
if env.bool("USE_S3", default=False):
    # Requires `pip install django-storages[s3]`; works with AWS S3, MinIO, Wasabi, DigitalOcean Spaces.
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_BUCKET"),
            "endpoint_url": env("S3_ENDPOINT_URL", default=None),
            "access_key": env("S3_ACCESS_KEY"),
            "secret_key": env("S3_SECRET_KEY"),
            "region_name": env("S3_REGION", default=None),
            "default_acl": "private",
            "querystring_auth": True,
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://heza")}

EMAIL_CONFIG = env.email("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Heza <no-reply@heza.rw>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
SUPPORT_EMAIL = env("SUPPORT_EMAIL", default="support@heza.rw")

MESSAGE_TAGS = {40: "danger"}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticatedOrReadOnly"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/min", "user": "300/min"},
}

# --- Security ---------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
if env("SECURE_SSL"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
RATELIMIT_ENABLED = env.bool("RATELIMIT_ENABLED", default=True)
USE_X_FORWARDED_FOR = env.bool("USE_X_FORWARDED_FOR", default=False)

# --- Business defaults -------------------------------------------------------
HEZA_CURRENCY = "RWF"
BOOKING_HOLD_MINUTES = env.int("BOOKING_HOLD_MINUTES", default=30)

# --- Payments ----------------------------------------------------------------
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", default="sandbox")
# The sandbox gateway is a test double; it is only on by default in DEBUG.
PAYMENT_PROVIDERS_ENABLED = env.list("PAYMENT_PROVIDERS_ENABLED", default=["sandbox", "flutterwave"] if DEBUG else ["flutterwave"])
SANDBOX_WEBHOOK_SECRET = env("SANDBOX_WEBHOOK_SECRET", default="sandbox-dev-secret")
SANDBOX_WEBHOOK_DELIVERY = env("SANDBOX_WEBHOOK_DELIVERY", default="inprocess")
FLUTTERWAVE_PUBLIC_KEY = env("FLUTTERWAVE_PUBLIC_KEY", default="")
FLUTTERWAVE_SECRET_KEY = env("FLUTTERWAVE_SECRET_KEY", default="")
FLUTTERWAVE_SECRET_HASH = env("FLUTTERWAVE_SECRET_HASH", default="")
FLUTTERWAVE_BASE_URL = env("FLUTTERWAVE_BASE_URL", default="https://api.flutterwave.com/v3")

# --- Messaging ---------------------------------------------------------------
SMS_BACKEND = env("SMS_BACKEND", default="apps.notifications.backends.ConsoleSMSBackend")
WHATSAPP_BACKEND = env("WHATSAPP_BACKEND", default="apps.notifications.backends.ConsoleWhatsAppBackend")
AFRICASTALKING_USERNAME = env("AFRICASTALKING_USERNAME", default="sandbox")
AFRICASTALKING_API_KEY = env("AFRICASTALKING_API_KEY", default="")
AFRICASTALKING_SENDER_ID = env("AFRICASTALKING_SENDER_ID", default="")

# --- Maps --------------------------------------------------------------------
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}

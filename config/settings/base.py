"""Settings shared by every environment.

Environment-specific overrides live in dev.py and prod.py. Anything secret or
deployment-specific comes from the environment - see .env.example.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    USE_S3=(bool, False),
    GUEST_LINK_MAX_AGE_DAYS=(int, 45),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")


# ---------------------------------------------------------------- applications

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",  # intcomma, for locale-aware money grouping
]

THIRD_PARTY_APPS = [
    "django_htmx",
    "django_celery_beat",
]

# Ordered roughly by dependency: foundations first, features after.
LOCAL_APPS = [
    "apps.core",           # base models, money, tenant scoping, Bali calendar
    "apps.accounts",       # custom User, email login, roles
    "apps.organizations",  # Organization (tenant), Membership, plan tier
    "apps.villas",         # Villa, photos, amenities
    "apps.guests",         # Guest, activity log, requests, portal links
    "apps.bookings",       # Booking, payments, unified calendar
    "apps.sync",           # Beds24 (premium) + iCal (basic) ingestion
    "apps.compliance",     # licence vault, STM reminders, action-needed view
    "apps.reporting",      # owner dashboard, daily staff view
    "apps.messaging",      # WhatsApp Cloud API outbound/inbound
    "apps.marketing",      # mini villa sites, direct booking, rate parity
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# ---------------------------------------------------------------- middleware

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",  # must precede CommonMiddleware
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    # Resolves the active Organization for the request and makes it available
    # as request.organization. Every tenant-scoped query depends on this.
    "apps.organizations.middleware.OrganizationMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.organizations.context_processors.organization",
            ],
        },
    },
]


# ---------------------------------------------------------------- database

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------- auth

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "villas:list"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Guests never get an account. They reach the portal through a signed, expiring
# link delivered over WhatsApp - see apps/guests/tokens.py.
GUEST_LINK_MAX_AGE_DAYS = env("GUEST_LINK_MAX_AGE_DAYS")


# ---------------------------------------------------------------- i18n / time

# Bilingual from day one. Do not hardcode user-facing strings - wrap them in
# gettext so both locales stay in sync. See CLAUDE.md.
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("id", "Bahasa Indonesia")]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True

# No USE_L10N here on purpose: Django dropped it in 5.0 and now always formats
# dates and numbers by the active locale. Setting it would read like a switch
# that does something when it does nothing.
#
# Thousand separators are NOT turned on globally either. That setting groups
# every number rendered in a template, ids and counts included, so an Indonesian
# page would print villa 1234 as "1.234" and break the JavaScript reading it
# back. Money is grouped where it is actually shown instead - the intcomma
# filter in templates, apps.bookings.services._money in Python.

# Bali is WITA (UTC+8). Stored timestamps are UTC; this is the display default
# and the basis for the STM 24-hour police-report deadline.
TIME_ZONE = "Asia/Makassar"
USE_TZ = True


# ---------------------------------------------------------------- static/media

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ---------------------------------------------------------------- celery

CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = env("REDIS_URL")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"


# ---------------------------------------------------------------- integrations

BEDS24_API_BASE = env("BEDS24_API_BASE", default="https://beds24.com/api/v2")
BEDS24_REFRESH_TOKEN = env("BEDS24_REFRESH_TOKEN", default="")
BEDS24_WEBHOOK_SECRET = env("BEDS24_WEBHOOK_SECRET", default="")

WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER", default="twilio")
WHATSAPP_ACCOUNT_SID = env("WHATSAPP_ACCOUNT_SID", default="")
WHATSAPP_AUTH_TOKEN = env("WHATSAPP_AUTH_TOKEN", default="")
WHATSAPP_FROM_NUMBER = env("WHATSAPP_FROM_NUMBER", default="")
WHATSAPP_WEBHOOK_SECRET = env("WHATSAPP_WEBHOOK_SECRET", default="")

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")

# Photos are served as WebP. If a source image cannot be converted, surface the
# failure rather than silently falling back to another format - see CLAUDE.md.
IMAGE_OUTPUT_FORMAT = "WEBP"
IMAGE_WEBP_QUALITY = 82


# -------------------------------------------------------------------- logging

# Every app writes through a logger named after its module ("apps.villas.views"
# and so on), so one switch here decides how much detail the whole project
# gives. The file is a rotating one on purpose - a chatty log left running for
# months should never be the thing that fills a small server's disk.
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_LEVEL = env("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detailed": {
            "format": "{asctime} {levelname:<7} {name} {funcName}:{lineno} - {message}",
            "style": "{",
        },
        "plain": {"format": "{levelname:<7} {name} - {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "app.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "detailed",
            "encoding": "utf-8",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "WARNING"},
    "loggers": {
        # Our own code, in full.
        "apps": {"handlers": ["console", "file"], "level": LOG_LEVEL, "propagate": False},
        # Django's own noise stays at WARNING; a request log line per page view
        # would bury everything above.
        "django": {"handlers": ["console", "file"], "level": "WARNING", "propagate": False},
        "django.request": {"handlers": ["console", "file"], "level": "ERROR", "propagate": False},
    },
}

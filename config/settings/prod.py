"""Production settings."""

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F403

DEBUG = False

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Compliance documents and guest ID scans are personal data under Indonesia's
# UU PDP and, for EU guests, GDPR. Keep them on private object storage - never
# in a public bucket or behind a guessable URL.
if env("USE_S3"):  # noqa: F405
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),  # noqa: F405
            "endpoint_url": env("AWS_S3_ENDPOINT_URL"),  # noqa: F405
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": 300,
        },
    }

if env("SENTRY_DSN", default=""):  # noqa: F405
    sentry_sdk.init(
        dsn=env("SENTRY_DSN"),  # noqa: F405
        integrations=[DjangoIntegration()],
        # Do not ship guest personal data to an error tracker.
        send_default_pii=False,
        traces_sample_rate=0.1,
    )

"""Local development settings."""

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
INTERNAL_IPS = ["127.0.0.1"]

# Print outbound mail and WhatsApp messages instead of sending them. Real sends
# in development risk burning template approvals and messaging real guests.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
WHATSAPP_PROVIDER = "console"

# Run Celery tasks inline so a local worker is not required.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

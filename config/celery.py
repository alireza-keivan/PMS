"""Celery entry point.

Background work falls into three buckets:
  - reconciliation  periodic re-pull from Beds24/iCal to catch missed webhooks
  - reminders       compliance expiry and STM police-report deadlines
  - messaging       outbound WhatsApp, which must respect the 24-hour window
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("villadash")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

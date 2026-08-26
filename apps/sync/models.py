"""Ingestion state for both sync tiers.

Everything upstream of this app is somebody else's system, so the design
assumes failure: raw payloads are kept, every run is logged, and reconciliation
re-pulls periodically to catch webhooks that never arrived.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel


class SyncAccount(TenantOwnedModel):
    """One connection to an upstream source.

    Premium tier: a Beds24 property account.
    Basic tier:   an iCal feed URL per villa per channel.
    """

    class Provider(models.TextChoices):
        BEDS24 = "beds24", "Beds24"
        ICAL = "ical", _("Calendar link")

    provider = models.CharField(max_length=20, choices=Provider.choices)
    villa = models.ForeignKey(
        "villas.Villa", on_delete=models.CASCADE, related_name="sync_accounts",
        null=True, blank=True,
        help_text=_("iCal feeds are per villa. A Beds24 account covers many."),
    )
    label = models.CharField(max_length=120, blank=True)

    # Beds24 issues a long-lived refresh token exchanged for short-lived access
    # tokens. Store the refresh token here, never the access token.
    beds24_property_id = models.CharField(max_length=60, blank=True)
    refresh_token = models.CharField(max_length=512, blank=True)

    ical_url = models.URLField(blank=True)
    ical_channel = models.CharField(
        max_length=20, blank=True, help_text=_("Which site this feed comes from.")
    )

    is_active = models.BooleanField(default=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["provider", "label"]

    def __str__(self):
        return self.label or f"{self.get_provider_display()} ({self.organization})"


class SyncRun(TenantOwnedModel):
    """One ingestion attempt. Kept for debugging and for the freshness badge.

    The dashboard reads the most recent successful run to tell the user how old
    their data is - which on the basic tier is genuinely hours, and is shown as
    such rather than implied to be live.
    """

    class Trigger(models.TextChoices):
        WEBHOOK = "webhook", _("Pushed by the source")
        SCHEDULED = "scheduled", _("Routine check")
        MANUAL = "manual", _("Started by hand")

    class Result(models.TextChoices):
        OK = "ok", _("Worked")
        PARTIAL = "partial", _("Partly worked")
        FAILED = "failed", _("Failed")

    account = models.ForeignKey(SyncAccount, on_delete=models.CASCADE, related_name="runs")
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    result = models.CharField(max_length=20, choices=Result.choices)
    bookings_created = models.PositiveIntegerField(default=0)
    bookings_updated = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class RawPayload(TenantOwnedModel):
    """Exactly what the upstream system sent, before we interpreted it.

    Kept because mapping bugs are only diagnosable against the original, and
    because replaying a payload is far cheaper than asking a provider to resend.
    """

    account = models.ForeignKey(
        SyncAccount, on_delete=models.CASCADE, related_name="payloads"
    )
    endpoint = models.CharField(max_length=120, blank=True)
    body = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

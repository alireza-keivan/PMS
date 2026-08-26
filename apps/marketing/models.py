"""Public villa pages, direct booking, and rate parity.

Google for Vacation Rentals and Stripe both run through Beds24 rather than
being built here - free booking links need a setting enabled plus a verified
Google Business Profile, and Stripe payouts go straight to the owner's own
account. See CLAUDE.md.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import Money, TenantOwnedModel


class RateSnapshot(TenantOwnedModel, Money):
    """One observed nightly rate for a villa on one channel (feature #12).

    Only channels we already receive data for through Beds24, plus our own
    direct rate. Competitor rate shopping is explicitly not built - it needs
    either a paid subscription or OTA scraping, which is against their terms.
    """

    villa = models.ForeignKey(
        "villas.Villa", on_delete=models.CASCADE, related_name="rate_snapshots"
    )
    channel = models.CharField(max_length=20)
    stay_date = models.DateField(db_index=True)
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-stay_date"]
        indexes = [models.Index(fields=["organization", "villa", "stay_date"])]


class Experience(TenantOwnedModel):
    """A local activity offered on the villa's experience page (feature #8).

    Commission is what makes this a revenue line for the owner rather than a
    list of links, so it is tracked per operator.
    """

    name_en = models.CharField(max_length=160)
    name_id = models.CharField(max_length=160, blank=True)
    description_en = models.TextField(blank=True)
    description_id = models.TextField(blank=True)
    operator_name = models.CharField(max_length=160, blank=True)
    operator_phone = models.CharField(max_length=32, blank=True)
    commission_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text=_("What the local operator pays the villa owner."),
    )
    photo = models.ImageField(upload_to="experiences/", blank=True)
    villas = models.ManyToManyField("villas.Villa", blank=True, related_name="experiences")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name_en"]

    def __str__(self):
        return self.name_en

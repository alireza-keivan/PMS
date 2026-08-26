"""Licence vault and police-report tracking.

The honesty rule matters more here than anywhere else in the product. This app
tracks what needs doing. It does not file anything with any government office,
and no label in it may suggest otherwise. See CLAUDE.md rule 2.
"""

from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel


class ComplianceDocument(TenantOwnedModel):
    """A licence or permit, with an expiry we watch (feature #14).

    Entirely internal - storing a document here involves no government system.
    """

    class Kind(models.TextChoices):
        NIB = "nib", _("Business licence (NIB)")
        PBG = "pbg", _("Building approval (PBG)")
        SLF = "slf", _("Building safety certificate (SLF)")
        TAX = "tax", _("Tax registration")
        OTHER = "other", _("Other document")

    villa = models.ForeignKey(
        "villas.Villa", on_delete=models.CASCADE, related_name="documents",
        null=True, blank=True, help_text=_("Leave empty if it covers the whole business."),
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    reference_number = models.CharField(max_length=120, blank=True)
    file = models.FileField(upload_to="compliance/%Y/")
    issued_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True, db_index=True)
    reminder_days = models.PositiveSmallIntegerField(
        default=60, help_text=_("Start warning this many days before it runs out.")
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["expires_on"]

    def __str__(self):
        return f"{self.get_kind_display()} - {self.villa or self.organization}"

    @property
    def needs_attention(self) -> bool:
        if not self.expires_on:
            return False
        return self.expires_on <= timezone.localdate() + timedelta(days=self.reminder_days)


class PoliceReport(TenantOwnedModel):
    """Tracks the 24-hour STM report for foreign guests (feature #15).

    This is a reminder only. The report itself is filed manually, on paper, at
    a police office - that is not something software changes, and this model
    must never be presented as having submitted anything.
    """

    class Status(models.TextChoices):
        NEEDED = "needed", _("Still to do")
        FILED = "filed", _("Marked as done by staff")
        NOT_REQUIRED = "not_required", _("Not needed")

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, related_name="police_reports"
    )
    guest = models.ForeignKey(
        "guests.Guest", on_delete=models.CASCADE, related_name="police_reports"
    )
    deadline = models.DateTimeField(
        db_index=True, help_text=_("24 hours after arrival, Bali time.")
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEEDED)

    # Recorded by whoever went to the police station, not verified by us.
    marked_done_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="police_reports_marked",
    )
    marked_done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["deadline"]
        verbose_name = _("police report reminder")

    @property
    def is_overdue(self) -> bool:
        return self.status == self.Status.NEEDED and self.deadline < timezone.now()

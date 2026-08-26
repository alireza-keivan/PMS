"""Balinese calendar awareness for staff scheduling (feature #4).

Nyepi, Galungan and Kuningan follow the 210-day Pawukon cycle and the Saka
lunar calendar, not the Gregorian one, so their dates cannot be derived with a
simple rule. Nyepi in particular is a full island shutdown - no flights, no
staff movement, no arrivals - which makes it an operational hard stop rather
than a decorative label on a calendar.

Dates are loaded from a maintained table rather than computed. Populate
`BaliHoliday` per year; do not attempt to calculate Pawukon dates in code.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class BaliHoliday(TimeStampedModel):
    """A local holiday affecting staffing and guest movement.

    Not tenant-scoped: these dates are the same for every operator on the island.
    """

    class Impact(models.TextChoices):
        SHUTDOWN = "shutdown", _("Island shutdown - nobody travels")
        NO_STAFF = "no_staff", _("Staff generally unavailable")
        REDUCED = "reduced", _("Reduced staff availability")
        INFO = "info", _("Worth knowing, no staffing impact")

    name = models.CharField(max_length=120)
    date = models.DateField(db_index=True)
    impact = models.CharField(max_length=20, choices=Impact.choices, default=Impact.INFO)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["date"]
        unique_together = [("name", "date")]
        verbose_name = _("Bali holiday")
        verbose_name_plural = _("Bali holidays")

    def __str__(self):
        return f"{self.name} ({self.date})"

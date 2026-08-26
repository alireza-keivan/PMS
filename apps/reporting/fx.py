"""Currency conversion, for display only.

Stored amounts always keep the currency they arrived in - see apps.core.Money.
This module converts at read time so an owner can see one consistent total,
without that conversion ever being written back to a booking.

Rates are entered manually to start with. A live rate API is worth adding only
once someone actually asks for daily accuracy; a stale rate on a summary screen
is a much smaller problem than a wrong number stored permanently.
"""

from decimal import Decimal

from django.db import models

from apps.core.models import TimeStampedModel


class ExchangeRate(TimeStampedModel):
    base_currency = models.CharField(max_length=3)
    quote_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=18, decimal_places=8)
    effective_on = models.DateField(db_index=True)

    class Meta:
        ordering = ["-effective_on"]
        unique_together = [("base_currency", "quote_currency", "effective_on")]

    def __str__(self):
        return f"{self.base_currency}/{self.quote_currency} {self.rate} ({self.effective_on})"


def convert(amount: Decimal, from_currency: str, to_currency: str, on_date) -> Decimal | None:
    """Return the converted amount, or None when no rate is on file.

    Returning None rather than guessing is deliberate: a report showing a blank
    with 'rate not set' is honest, one showing a made-up figure is not.
    """
    if from_currency == to_currency:
        return amount
    rate = (
        ExchangeRate.objects.filter(
            base_currency=from_currency,
            quote_currency=to_currency,
            effective_on__lte=on_date,
        )
        .order_by("-effective_on")
        .first()
    )
    return amount * rate.rate if rate else None

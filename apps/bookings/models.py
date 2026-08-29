"""Bookings from every channel, in one place.

A Booking is our record of a stay, not the OTA's. It may arrive through Beds24
with full detail, or through an iCal feed as nothing more than a blocked date
range. `source_detail` records which, so no screen has to guess how much it can
truthfully say about a given row.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import Money, TenantOwnedModel


class Booking(TenantOwnedModel):
    class Channel(models.TextChoices):
        AIRBNB = "airbnb", "Airbnb"
        BOOKING_COM = "booking_com", "Booking.com"
        DIRECT = "direct", _("Direct")
        WHATSAPP = "whatsapp", "WhatsApp"
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", _("Confirmed")
        CANCELLED = "cancelled", _("Cancelled")
        BLOCKED = "blocked", _("Not available")  # iCal blocks with no guest behind them

    class SourceDetail(models.TextChoices):
        """How complete this row actually is. Drives what the UI may claim."""

        FULL = "full", _("Full details")        # Beds24: guest, price, messages
        DATES_ONLY = "dates_only", _("Dates only")  # iCal: availability, nothing more
        MANUAL = "manual", _("Entered by staff")

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    villa = models.ForeignKey(
        "villas.Villa", on_delete=models.PROTECT, related_name="bookings"
    )
    room = models.ForeignKey(
        "villas.Room", on_delete=models.PROTECT, null=True, blank=True, related_name="bookings",
        help_text=_(
            "Optional - only set once a villa's rooms are defined individually. PROTECT (not "
            "SET_NULL) on purpose: the calendar only draws bookings on room rows, so a booking "
            "silently losing its room would silently disappear from view - see apps/bookings/"
            "services.py's build_calendar_rows()."
        ),
    )
    guest = models.ForeignKey(
        "guests.Guest", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bookings",
        help_text=_("Absent on calendar-only bookings - the feed carries no name."),
    )

    check_in = models.DateField(db_index=True)
    check_out = models.DateField(db_index=True)
    guest_count = models.PositiveSmallIntegerField(default=1)

    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.OTHER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONFIRMED)
    source_detail = models.CharField(
        max_length=20, choices=SourceDetail.choices, default=SourceDetail.DATES_ONLY
    )

    # Identity in the upstream system, so repeated syncs update rather than duplicate.
    external_id = models.CharField(max_length=120, blank=True, db_index=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-check_in"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(check_out__gt=models.F("check_in")),
                name="booking_checkout_after_checkin",
            ),
            models.UniqueConstraint(
                fields=["organization", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_external_booking_per_org",
            ),
        ]
        indexes = [models.Index(fields=["organization", "check_in", "check_out"])]

    def __str__(self):
        who = self.guest.full_name if self.guest else _("Not available")
        return f"{who} - {self.villa} ({self.check_in} to {self.check_out})"

    def clean(self):
        super().clean()
        if self.room_id and self.room.villa_id != self.villa_id:
            raise ValidationError({"room": _("That room doesn't belong to this booking's villa.")})

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @property
    def has_guest_details(self) -> bool:
        """False for calendar-only rows. Gate guest-dependent features on this."""
        return self.source_detail == self.SourceDetail.FULL and self.guest_id is not None


class BookingPayment(TenantOwnedModel, Money):
    """Money against a booking, in the currency it was actually received in.

    Never present on calendar-only bookings - iCal feeds carry no pricing.
    """

    class Kind(models.TextChoices):
        PAYOUT = "payout", _("Paid by the booking site")
        DIRECT = "direct", _("Paid directly")
        DEPOSIT = "deposit", _("Deposit")
        REFUND = "refund", _("Refund")

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PAYOUT)
    received_on = models.DateField(null=True, blank=True)
    is_outstanding = models.BooleanField(
        default=False, help_text=_("Still owed - shows on the daily staff view.")
    )
    stripe_payment_intent = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-received_on"]

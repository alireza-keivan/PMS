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
    )
    photo = models.ImageField(upload_to="experiences/", blank=True)
    villas = models.ManyToManyField("villas.Villa", blank=True, related_name="experiences")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name_en"]

    def __str__(self):
        return self.name_en


class BookingEnquiry(TenantOwnedModel):
    """Someone asked to stay, from a villa's own public page (features #11, #13).

    Deliberately not a Booking, and deliberately not connected to one. Nothing
    on the public side may write to live inventory - CLAUDE.md rule 5 - so this
    records what the visitor asked for and stops there. The dates were checked
    against real bookings before the row was written, but no room is held and
    no calendar changes: an operator still reads it and decides. Two people can
    therefore enquire about the same nights, which is correct - an unanswered
    enquiry is not a reservation.

    No payment fields either. Direct payment (feature #11) runs through the
    owner's own Stripe account via Beds24 and needs a registered business
    behind it, so it is not part of this form.
    """

    villa = models.ForeignKey(
        "villas.Villa", on_delete=models.CASCADE, related_name="booking_enquiries"
    )
    room_category = models.ForeignKey(
        "villas.RoomCategory", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="booking_enquiries",
        help_text=_("Which room type the visitor was looking at."),
    )

    check_in = models.DateField()
    check_out = models.DateField()
    guest_count = models.PositiveSmallIntegerField(default=1)

    guest_name = models.CharField(max_length=160)
    guest_email = models.EmailField(blank=True)
    guest_phone = models.CharField(
        max_length=32, blank=True, help_text=_("WhatsApp number, if they left one.")
    )
    message = models.TextField(blank=True)

    # What the page quoted while they were filling the form in, in whole
    # rupiah. Kept so a later argument about the price can be settled against
    # what the guest was actually shown, not against today's rate.
    quoted_total = models.PositiveBigIntegerField(null=True, blank=True)

    is_handled = models.BooleanField(
        default=False, help_text=_("Someone has replied to this.")
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "villa", "check_in"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(check_out__gt=models.F("check_in")),
                name="enquiry_checkout_after_checkin",
            ),
        ]
        verbose_name_plural = _("booking enquiries")

    def __str__(self):
        return f"{self.guest_name} - {self.villa} ({self.check_in} to {self.check_out})"

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

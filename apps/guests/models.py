"""Guests, what they asked for, and what they did.

Two things are true at once here, and they are independent:

  1. Guests never hold an account. They reach the portal through a signed,
     expiring link sent over WhatsApp - no password, no signup, nothing to
     forget during a five-day stay.

  2. We still keep a durable record of who they were and what they did. The
     link is only the door; the history persists on the Guest row behind it.

That combination is what makes questions like "which nationalities book tours,
and which tours" answerable. Nationality is already on file because the STM
police report (feature #15) requires it for foreign guests, so the analysis
costs no extra data collection.

Privacy: these rows are personal data under Indonesia's UU PDP, and under GDPR
for EU guests. `Guest.retain_until` exists so records can be aged out on a
schedule rather than accumulating forever - wire it to a Celery job before
launch, and keep aggregate analysis to the fields actually needed.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel
from apps.guests.constants import NATIONALITY_CHOICES


class Guest(TenantOwnedModel):
    """A person, persisting across stays.

    Deduplicated on email or phone within an organization so a repeat visitor
    accumulates one history rather than a new row per booking.
    """

    full_name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(
        max_length=32, blank=True, help_text=_("WhatsApp number, international format.")
    )
    nationality = models.CharField(
        max_length=2,
        blank=True,
        db_index=True,
        choices=NATIONALITY_CHOICES,
        help_text=_("ISO 3166-1 alpha-2. Required for the STM police report."),
    )
    preferred_language = models.CharField(max_length=5, blank=True)

    # Denormalised for fast segmenting; recalculated when a booking closes.
    total_stays = models.PositiveIntegerField(default=0)
    first_seen = models.DateField(null=True, blank=True)
    last_seen = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True, help_text=_("Internal. Never shown to the guest."))
    retain_until = models.DateField(
        null=True,
        blank=True,
        help_text=_("Delete or anonymise this record after this date."),
    )

    class Meta:
        ordering = ["-last_seen"]
        indexes = [
            models.Index(fields=["organization", "nationality"]),
            models.Index(fields=["organization", "email"]),
            models.Index(fields=["organization", "phone"]),
        ]

    def __str__(self):
        return self.full_name

    @property
    def is_returning(self) -> bool:
        return self.total_stays > 1


class GuestActivity(TenantOwnedModel):
    """Append-only log of everything a guest did.

    This is the analysis substrate. One row per meaningful action, always
    carrying the guest, the villa and the moment - so "a Russian guest booked a
    Monkey Forest tour on 14 March" is a plain filter, not a reconstruction.

    Never update or delete rows here as part of normal operation; correct by
    appending. Deletion belongs only to the retention job.
    """

    class Kind(models.TextChoices):
        PORTAL_OPENED = "portal_opened", _("Opened their page")
        REQUEST_MADE = "request_made", _("Asked for something")
        EXPERIENCE_VIEWED = "experience_viewed", _("Looked at a local activity")
        EXPERIENCE_BOOKED = "experience_booked", _("Booked a local activity")
        FEEDBACK_GIVEN = "feedback_given", _("Left private feedback")
        MESSAGE_SENT = "message_sent", _("Sent a message")

    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="activity")
    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="activity",
    )
    villa = models.ForeignKey(
        "villas.Villa", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="guest_activity",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)

    # What the action referred to: a tour name, a request type, a rating.
    subject = models.CharField(max_length=200, blank=True)
    # Anything else worth keeping without a schema change - price, operator,
    # party size. Queryable via JSONB.
    detail = models.JSONField(default=dict, blank=True)

    occurred_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name_plural = _("guest activity")
        indexes = [
            models.Index(fields=["organization", "kind", "occurred_at"]),
            models.Index(fields=["guest", "occurred_at"]),
        ]

    def __str__(self):
        return f"{self.guest} - {self.get_kind_display()} ({self.occurred_at:%Y-%m-%d})"


class GuestRequest(TenantOwnedModel):
    """Something the guest asked for from their phone (feature #7).

    Creating one of these triggers an outbound WhatsApp message to the
    responsible staff member. The dashboard entry alone is not the delivery
    mechanism - see apps/messaging/.
    """

    class Kind(models.TextChoices):
        CLEANING = "cleaning", _("Cleaning")
        REPAIR = "repair", _("Something is broken")
        CHEF = "chef", _("Private chef")
        GROCERIES = "groceries", _("Grocery stocking")
        TRANSFER = "transfer", _("Airport transfer")
        OTHER = "other", _("Something else")

    class Status(models.TextChoices):
        NEW = "new", _("New")
        SEEN = "seen", _("Seen by staff")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, related_name="requests"
    )
    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="requests")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_to = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_requests",
    )
    notified_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When staff were actually messaged.")
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} - {self.guest}"


class GuestFeedback(TenantOwnedModel):
    """Private mid-stay check-in (feature #9).

    Deliberately not a review request. Happy guests are invited to review
    publicly; unhappy ones are routed to the owner so the problem can be fixed
    while they are still there.

    Any loyalty discount is for booking direct next time and is never
    conditioned on leaving a review, or on the review being positive - Airbnb
    bans that outright and it puts the client's listing at risk.
    """

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, related_name="feedback"
    )
    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="feedback")
    rating = models.PositiveSmallIntegerField(help_text=_("1 to 5."))
    comment = models.TextField(blank=True)
    escalated_to_owner = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = _("guest feedback")

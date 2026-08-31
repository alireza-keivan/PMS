"""Guest record maintenance and activity logging.

`log_activity` is the single entry point for writing to the activity trail.
Call it from views and tasks rather than creating GuestActivity rows directly,
so every event lands with consistent tenant, villa and timestamp fields.
"""

from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.bookings.models import BookingPayment
from apps.guests.models import Guest, GuestActivity


def find_or_create_guest(organization, *, full_name, email="", phone="", nationality=""):
    """Match a returning guest on email or phone before creating a new record.

    Matching is scoped to the organization - two operators never share guest
    rows, even for the same person.
    """
    lookup = Guest.objects.filter(organization=organization)
    guest = None
    if email:
        guest = lookup.filter(email__iexact=email).first()
    if guest is None and phone:
        guest = lookup.filter(phone=phone).first()

    if guest is None:
        return Guest.objects.create(
            organization=organization,
            full_name=full_name,
            email=email,
            phone=phone,
            nationality=nationality,
            first_seen=timezone.localdate(),
        )

    # Fill gaps on an existing record without overwriting what is already known.
    updates = {}
    if nationality and not guest.nationality:
        updates["nationality"] = nationality
    if email and not guest.email:
        updates["email"] = email
    if phone and not guest.phone:
        updates["phone"] = phone
    if updates:
        Guest.objects.filter(pk=guest.pk).update(**updates)
    return guest


def guest_spend_summary(guest) -> dict:
    """Total paid and still-owed across every one of this guest's bookings.

    Same shape as apps.bookings.services.payment_summary_by_booking, just
    aggregated across the whole guest rather than one booking at a time - for
    the guest profile's "total expenditure" / "amount due" fields.
    """
    row = (
        BookingPayment.objects.filter(organization=guest.organization, booking__guest=guest)
        .aggregate(
            total_amount=Sum("amount", filter=~Q(kind=BookingPayment.Kind.REFUND)),
            amount_owed=Sum("amount", filter=Q(is_outstanding=True)),
            currency=Max("currency"),
        )
    )
    return row


def log_activity(guest, kind, *, booking=None, villa=None, subject="", detail=None):
    """Append one event to the guest's history."""
    return GuestActivity.objects.create(
        organization=guest.organization,
        guest=guest,
        booking=booking,
        villa=villa or (booking.villa if booking else None),
        kind=kind,
        subject=subject,
        detail=detail or {},
        occurred_at=timezone.now(),
    )

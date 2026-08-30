"""Booking is the busiest table in the product. These tests cover the three
guarantees the rest of the app leans on: dates are always sane, syncing the
same upstream booking twice never duplicates it, and a row honestly reports
how much it actually knows.
"""

from datetime import date, timedelta

import pytest
from django.db import IntegrityError, transaction

from apps.bookings.models import Booking, BookingPayment
from apps.guests.services import find_or_create_guest


def _dates(nights=3, start=None):
    start = start or date.today()
    return start, start + timedelta(days=nights)


def test_checkout_must_be_after_checkin(org, villa):
    check_in, check_out = _dates()
    with pytest.raises(IntegrityError), transaction.atomic():
        Booking.objects.create(
            organization=org, villa=villa, check_in=check_out, check_out=check_in
        )


def test_same_day_checkin_and_checkout_is_rejected(org, villa):
    same_day = date.today()
    with pytest.raises(IntegrityError), transaction.atomic():
        Booking.objects.create(organization=org, villa=villa, check_in=same_day, check_out=same_day)


def test_external_id_is_unique_per_organization(org, villa):
    check_in, check_out = _dates()
    Booking.objects.create(
        organization=org, villa=villa, check_in=check_in, check_out=check_out,
        external_id="beds24-123",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Booking.objects.create(
            organization=org, villa=villa, check_in=check_in, check_out=check_out,
            external_id="beds24-123",
        )


def test_two_organizations_can_reuse_the_same_external_id(org, other_org, villa):
    """A collision in someone else's Beds24 account must never block ours."""
    other_villa_check_in, other_villa_check_out = _dates()
    from apps.villas.models import Villa

    other_villa = Villa.objects.create(organization=other_org, name="Other Villa", slug="other")

    Booking.objects.create(
        organization=org, villa=villa, check_in=other_villa_check_in,
        check_out=other_villa_check_out, external_id="shared-id",
    )
    # Should not raise.
    Booking.objects.create(
        organization=other_org, villa=other_villa, check_in=other_villa_check_in,
        check_out=other_villa_check_out, external_id="shared-id",
    )
    assert Booking.objects.filter(external_id="shared-id").count() == 2


def test_multiple_blank_external_ids_are_allowed(org, villa):
    """Manual/direct bookings have no external_id at all - the uniqueness
    constraint must not treat repeated blanks as a collision."""
    check_in, check_out = _dates()
    Booking.objects.create(organization=org, villa=villa, check_in=check_in, check_out=check_out)
    Booking.objects.create(
        organization=org, villa=villa,
        check_in=check_in + timedelta(days=10), check_out=check_out + timedelta(days=10),
    )
    assert Booking.objects.filter(external_id="").count() == 2


def test_nights_property(org, villa):
    check_in, check_out = _dates(nights=5)
    booking = Booking.objects.create(organization=org, villa=villa, check_in=check_in, check_out=check_out)
    assert booking.nights == 5


@pytest.mark.parametrize(
    "source_detail,has_guest,expected",
    [
        (Booking.SourceDetail.FULL, True, True),
        (Booking.SourceDetail.FULL, False, False),
        (Booking.SourceDetail.DATES_ONLY, True, False),
        (Booking.SourceDetail.DATES_ONLY, False, False),
        (Booking.SourceDetail.MANUAL, True, True),
        (Booking.SourceDetail.MANUAL, False, False),
    ],
)
def test_has_guest_details_requires_both_full_detail_and_a_guest(
    org, villa, source_detail, has_guest, expected
):
    check_in, check_out = _dates()
    guest = find_or_create_guest(org, full_name="Test Guest") if has_guest else None
    booking = Booking.objects.create(
        organization=org, villa=villa, check_in=check_in, check_out=check_out,
        source_detail=source_detail, guest=guest,
    )
    assert booking.has_guest_details is expected


def test_deleting_a_booking_does_not_delete_the_guest(org, villa):
    guest = find_or_create_guest(org, full_name="Test Guest")
    check_in, check_out = _dates()
    booking = Booking.objects.create(
        organization=org, villa=villa, check_in=check_in, check_out=check_out, guest=guest,
    )
    booking.delete()
    guest.refresh_from_db()  # must not raise


def test_payment_keeps_its_original_currency(org, villa):
    check_in, check_out = _dates()
    booking = Booking.objects.create(organization=org, villa=villa, check_in=check_in, check_out=check_out)
    payment = BookingPayment.objects.create(
        organization=org, booking=booking, amount="1500000.00", currency="IDR",
    )
    assert payment.currency == "IDR"
    assert str(payment.amount) == "1500000.00"

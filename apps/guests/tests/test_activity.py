"""Proves the two things the guest design has to get right:

  1. Guests have no account, but their history still persists and is queryable.
  2. One operator can never see another operator's guests.
"""

from datetime import date, timedelta

import pytest

from apps.bookings.models import Booking
from apps.guests.models import Guest, GuestActivity
from apps.guests.services import find_or_create_guest, log_activity
from apps.guests.tokens import make_token, read_token
from apps.organizations.models import Organization
from apps.villas.models import Villa


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Canggu Villas", slug="canggu")


@pytest.fixture
def villa(org):
    return Villa.objects.create(organization=org, name="Villa Melati", slug="melati")


def test_guest_activity_answers_nationality_questions(org, villa):
    """The motivating question: which nationalities booked which tours, and when."""
    guest = find_or_create_guest(
        org, full_name="Anna Petrova", email="anna@example.com", nationality="RU"
    )
    booking = Booking.objects.create(
        organization=org,
        villa=villa,
        guest=guest,
        check_in=date(2026, 3, 12),
        check_out=date(2026, 3, 19),
        source_detail=Booking.SourceDetail.FULL,
    )
    log_activity(
        guest,
        GuestActivity.Kind.EXPERIENCE_BOOKED,
        booking=booking,
        subject="Monkey Forest tour",
        detail={"price": "450000", "currency": "IDR", "party_size": 2},
    )

    russian_tour_bookings = GuestActivity.objects.filter(
        organization=org,
        kind=GuestActivity.Kind.EXPERIENCE_BOOKED,
        guest__nationality="RU",
    )
    assert russian_tour_bookings.count() == 1
    activity = russian_tour_bookings.get()
    assert activity.subject == "Monkey Forest tour"
    assert activity.detail["party_size"] == 2
    assert activity.villa == villa


def test_returning_guest_is_matched_not_duplicated(org):
    first = find_or_create_guest(org, full_name="Anna Petrova", email="anna@example.com")
    second = find_or_create_guest(
        org, full_name="Anna Petrova", email="ANNA@example.com", nationality="RU"
    )
    assert first.pk == second.pk
    assert Guest.objects.filter(organization=org).count() == 1
    # A later booking can fill in a field the first one lacked.
    second.refresh_from_db()
    assert second.nationality == "RU"


def test_guests_never_leak_between_operators(org):
    other = Organization.objects.create(name="Ubud Retreats", slug="ubud")
    find_or_create_guest(org, full_name="Anna Petrova", email="anna@example.com")
    same_person_elsewhere = find_or_create_guest(
        other, full_name="Anna Petrova", email="anna@example.com"
    )

    # Same human, two operators, two separate records - no cross-tenant match.
    assert Guest.objects.count() == 2
    assert Guest.objects.for_organization(org).count() == 1
    assert same_person_elsewhere.organization == other


def test_portal_link_round_trips_without_an_account(org, villa):
    booking = Booking.objects.create(
        organization=org,
        villa=villa,
        check_in=date.today(),
        check_out=date.today() + timedelta(days=3),
    )
    token = make_token(booking)
    assert read_token(token) == str(booking.reference)
    assert read_token("not-a-real-token") is None


def test_calendar_only_booking_admits_it_has_no_guest(org, villa):
    """Basic-tier rows must not pretend to carry guest detail."""
    booking = Booking.objects.create(
        organization=org,
        villa=villa,
        check_in=date.today(),
        check_out=date.today() + timedelta(days=2),
        source_detail=Booking.SourceDetail.DATES_ONLY,
        status=Booking.Status.BLOCKED,
    )
    assert booking.has_guest_details is False
    assert org.has_live_sync is False

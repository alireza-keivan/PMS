"""The dashboard is the first real screen in the product, so the numbers on
it have to be right, not just present. These tests check the two things a
wrong dashboard would get away with silently: mixing up currencies, and
showing one operator's money to another.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking, BookingPayment
from apps.organizations.models import Membership
from apps.reporting.fx import ExchangeRate
from apps.villas.models import Villa


@pytest.fixture
def owner_client(client, org, user):
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OWNER)
    client.force_login(user)
    return client


def test_dashboard_requires_login(client, db):
    response = client.get(reverse("reporting:dashboard"))
    assert response.status_code == 302
    assert "login" in response.url


def test_user_with_no_membership_sees_the_no_organization_state(client, db):
    lonely_user = User.objects.create_user(email="nobody@example.com", password="testpass123")
    client.force_login(lonely_user)
    response = client.get(reverse("reporting:dashboard"))
    assert response.status_code == 200
    assert response.context["no_organization"] is True


def test_revenue_converts_foreign_currency_using_the_stored_rate(owner_client, org, villa):
    ExchangeRate.objects.create(
        base_currency="USD", quote_currency="IDR", rate="15000", effective_on="2020-01-01",
    )
    today = timezone.localdate()
    booking = Booking.objects.create(
        organization=org, villa=villa, check_in=today - timedelta(days=20), check_out=today - timedelta(days=15),
    )
    BookingPayment.objects.create(
        organization=org, booking=booking, kind=BookingPayment.Kind.PAYOUT,
        amount="100.00", currency="USD", received_on=today, is_outstanding=False,
    )

    response = owner_client.get(reverse("reporting:dashboard"))
    assert response.context["revenue_this_month"] == 1_500_000
    assert response.context["revenue_unconverted_count"] == 0


def test_payment_with_no_exchange_rate_is_excluded_and_flagged(owner_client, org, villa):
    """No EUR rate is seeded here - the total must not silently include a
    guessed conversion, and the page must say something was left out.
    """
    today = timezone.localdate()
    booking = Booking.objects.create(organization=org, villa=villa, check_in=today, check_out=today + timedelta(days=3))
    BookingPayment.objects.create(
        organization=org, booking=booking, kind=BookingPayment.Kind.PAYOUT,
        amount="200.00", currency="EUR", received_on=today, is_outstanding=False,
    )

    response = owner_client.get(reverse("reporting:dashboard"))
    assert response.context["revenue_this_month"] == 0
    assert response.context["revenue_unconverted_count"] == 1


def test_dashboard_never_shows_another_organizations_revenue(owner_client, org, other_org, villa):
    """The bug class that matters most here: a query missing an organization
    filter would leak one operator's money into another's total.
    """
    today = timezone.localdate()
    other_villa = Villa.objects.create(organization=other_org, name="Someone Else's Villa", slug="other")
    other_booking = Booking.objects.create(
        organization=other_org, villa=other_villa, check_in=today - timedelta(days=1), check_out=today + timedelta(days=2),
    )
    BookingPayment.objects.create(
        organization=other_org, booking=other_booking, kind=BookingPayment.Kind.PAYOUT,
        amount="999000000.00", currency="IDR", received_on=today, is_outstanding=False,
    )

    response = owner_client.get(reverse("reporting:dashboard"))
    assert response.context["revenue_this_month"] == 0


def test_occupancy_counts_only_bookings_covering_today(owner_client, org, villa):
    today = timezone.localdate()
    Booking.objects.create(  # covers today
        organization=org, villa=villa, check_in=today - timedelta(days=1), check_out=today + timedelta(days=2),
    )
    response = owner_client.get(reverse("reporting:dashboard"))
    assert response.context["occupied_villas"] == 1
    assert response.context["total_villas"] == 1
    assert response.context["occupancy_percent"] == 100


def test_cancelled_booking_does_not_count_as_occupying(owner_client, org, villa):
    today = timezone.localdate()
    Booking.objects.create(
        organization=org, villa=villa, check_in=today - timedelta(days=1), check_out=today + timedelta(days=2),
        status=Booking.Status.CANCELLED,
    )
    response = owner_client.get(reverse("reporting:dashboard"))
    assert response.context["occupied_villas"] == 0

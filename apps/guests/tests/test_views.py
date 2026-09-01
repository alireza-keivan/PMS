"""guests:detail is a per-person profile page - it needs to pull together
their bookings, requests, feedback, and police-report reminders rather than
showing an empty shell.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking, BookingPayment
from apps.compliance.models import PoliceReport
from apps.guests.models import Guest, GuestActivity, GuestFeedback, GuestRequest


@pytest.fixture
def owner_client(client, org, user, make_membership):
    make_membership(user, org, manager=True)
    client.force_login(user)
    return client


def test_guest_detail_shows_their_bookings(owner_client, org, villa, guest):
    today = timezone.localdate()
    Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=today, check_out=today + timedelta(days=3),
    )
    response = owner_client.get(reverse("guests:detail", args=[guest.pk]))
    assert response.status_code == 200
    assert list(response.context["bookings"]) == list(guest.bookings.all())


def test_guest_detail_shows_their_requests_feedback_and_police_reports(owner_client, org, villa, guest):
    today = timezone.localdate()
    booking = Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=today, check_out=today + timedelta(days=3),
    )
    GuestRequest.objects.create(organization=org, booking=booking, guest=guest, kind="cleaning")
    GuestFeedback.objects.create(organization=org, booking=booking, guest=guest, rating=5)
    PoliceReport.objects.create(
        organization=org, booking=booking, guest=guest,
        deadline=timezone.now() + timedelta(hours=20),
    )
    GuestActivity.objects.create(
        organization=org, guest=guest, booking=booking, kind=GuestActivity.Kind.PORTAL_OPENED,
        occurred_at=timezone.now(),
    )

    response = owner_client.get(reverse("guests:detail", args=[guest.pk]))
    assert response.status_code == 200
    assert response.context["requests"].count() == 1
    assert response.context["feedback_entries"].count() == 1
    assert response.context["police_reports"].count() == 1
    assert response.context["recent_activity"].count() == 1


def test_guest_detail_shows_total_expenditure_and_amount_due_to_owners(owner_client, org, villa, guest):
    today = timezone.localdate()
    booking = Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=today, check_out=today + timedelta(days=3),
    )
    BookingPayment.objects.create(
        organization=org, booking=booking, amount=1_500_000, currency="IDR",
    )
    BookingPayment.objects.create(
        organization=org, booking=booking, amount=500_000, currency="IDR", is_outstanding=True,
    )

    response = owner_client.get(reverse("guests:detail", args=[guest.pk]))
    assert response.context["total_expenditure"] == "Rp 2,000,000"
    assert response.context["amount_due"] == "Rp 500,000"


def test_guest_detail_hides_money_from_staff_without_money_permission(org, user, villa, guest, make_membership):
    from django.test import Client

    make_membership(user, org, manager=False)
    today = timezone.localdate()
    booking = Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=today, check_out=today + timedelta(days=3),
    )
    BookingPayment.objects.create(organization=org, booking=booking, amount=1_500_000, currency="IDR")

    client = Client()
    client.force_login(user)
    response = client.get(reverse("guests:detail", args=[guest.pk]))
    assert response.context["can_see_money"] is False
    assert response.context["total_expenditure"] is None


def test_cannot_view_another_organizations_guest(owner_client, other_org):
    other_guest = Guest.objects.create(organization=other_org, full_name="Not mine")
    response = owner_client.get(reverse("guests:detail", args=[other_guest.pk]))
    assert response.status_code == 404

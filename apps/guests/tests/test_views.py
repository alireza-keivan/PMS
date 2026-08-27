"""The guest directory is read-only and tenant-scoped - the main things worth
proving are that one operator never sees another's guests, and that a guest's
detail page actually pulls together their bookings, requests, feedback, and
police-report reminders rather than showing an empty shell.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking
from apps.compliance.models import PoliceReport
from apps.guests.models import Guest, GuestActivity, GuestFeedback, GuestRequest
from apps.organizations.models import Membership


@pytest.fixture
def owner_client(client, org, user):
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OWNER)
    client.force_login(user)
    return client


def test_guest_list_shows_only_this_organizations_guests(owner_client, org, other_org):
    mine = Guest.objects.create(organization=org, full_name="Mine")
    Guest.objects.create(organization=other_org, full_name="Not mine")

    response = owner_client.get(reverse("guests:list"))
    assert list(response.context["guests"]) == [mine]


def test_guest_list_searches_by_name_email_and_phone(owner_client, org):
    Guest.objects.create(organization=org, full_name="Made Wijaya", email="made@example.com")
    Guest.objects.create(organization=org, full_name="Someone Else", phone="+61400000000")

    response = owner_client.get(reverse("guests:list"), {"q": "made"})
    names = [g.full_name for g in response.context["guests"]]
    assert names == ["Made Wijaya"]


def test_no_organization_shows_the_placeholder_state(client, user):
    client.force_login(user)
    response = client.get(reverse("guests:list"))
    assert response.context["no_organization"] is True


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


def test_cannot_view_another_organizations_guest(owner_client, other_org):
    other_guest = Guest.objects.create(organization=other_org, full_name="Not mine")
    response = owner_client.get(reverse("guests:detail", args=[other_guest.pk]))
    assert response.status_code == 404

"""guests:list is a reservation search (one row per booking, grouped by
date), not a guest directory - the main things worth proving are that it
scopes and filters correctly and never leaks across organizations or
unassigned villas. guests:detail is still a per-person profile page, and
still needs to pull together their bookings, requests, feedback, and
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


def _booking(org, villa, guest=None, offset=0, nights=3, **kwargs):
    today = timezone.localdate()
    check_in = today + timedelta(days=offset)
    return Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=check_in, check_out=check_in + timedelta(days=nights),
        **kwargs,
    )


def test_reservation_list_shows_only_this_organizations_bookings(owner_client, org, other_org, villa):
    from apps.villas.models import Villa

    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    mine = _booking(org, villa)
    _booking(other_org, other_villa)

    response = owner_client.get(reverse("guests:list"))
    all_bookings = [row["booking"] for group in response.context["groups"] for row in group["rows"]]
    assert all_bookings == [mine]


def test_reservation_list_searches_by_guest_name(owner_client, org, villa, guest):
    Guest.objects.create(organization=org, full_name="Someone Else")
    _booking(org, villa, guest=guest)  # guest fixture is "Wayan Guest"

    response = owner_client.get(reverse("guests:list"), {"guest_name": "wayan"})
    all_bookings = [row["booking"] for group in response.context["groups"] for row in group["rows"]]
    assert len(all_bookings) == 1
    assert all_bookings[0].guest == guest


def test_reservation_list_groups_by_check_in_date(owner_client, org, villa):
    _booking(org, villa, offset=0)
    _booking(org, villa, offset=0)  # same date, groups together
    _booking(org, villa, offset=5)

    response = owner_client.get(reverse("guests:list"), {"date_to": (timezone.localdate() + timedelta(days=10)).isoformat()})
    groups = response.context["groups"]
    assert len(groups) == 2
    assert len(groups[0]["rows"]) == 2


def test_reservation_list_filters_by_status(owner_client, org, villa):
    _booking(org, villa, status=Booking.Status.CONFIRMED)
    _booking(org, villa, status=Booking.Status.BLOCKED)

    response = owner_client.get(reverse("guests:list"), {"status": Booking.Status.BLOCKED})
    all_bookings = [row["booking"] for group in response.context["groups"] for row in group["rows"]]
    assert len(all_bookings) == 1
    assert all_bookings[0].status == Booking.Status.BLOCKED


def test_reservation_list_filters_by_villa(owner_client, org, villa):
    from apps.villas.models import Villa

    other_villa = Villa.objects.create(organization=org, name="Other Villa", slug="other-villa")
    _booking(org, villa)
    _booking(org, other_villa)

    response = owner_client.get(reverse("guests:list"), {"villa": villa.pk})
    all_bookings = [row["booking"] for group in response.context["groups"] for row in group["rows"]]
    assert len(all_bookings) == 1
    assert all_bookings[0].villa == villa


def test_reservation_list_villa_filter_cannot_escape_staff_scoping(org, user, villa):
    from apps.villas.models import Villa

    other_villa = Villa.objects.create(organization=org, name="Not Assigned", slug="not-assigned")
    membership = Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)
    membership.villas.add(villa)
    _booking(org, other_villa)

    from django.test import Client

    client = Client()
    client.force_login(user)
    response = client.get(reverse("guests:list"), {"villa": other_villa.pk})
    all_bookings = [row["booking"] for group in response.context["groups"] for row in group["rows"]]
    assert all_bookings == []


def test_staff_scoped_to_specific_villas_only_sees_those_reservations(org, user, villa):
    from apps.villas.models import Villa

    other_villa = Villa.objects.create(organization=org, name="Not Assigned", slug="not-assigned")
    membership = Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)
    membership.villas.add(villa)
    _booking(org, villa)
    _booking(org, other_villa)

    from django.test import Client

    client = Client()
    client.force_login(user)
    response = client.get(reverse("guests:list"))
    all_bookings = [row["booking"] for group in response.context["groups"] for row in group["rows"]]
    assert len(all_bookings) == 1
    assert all_bookings[0].villa == villa


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

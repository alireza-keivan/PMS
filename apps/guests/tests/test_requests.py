"""The staff queue at guests:requests.

This page is how staff find out a guest asked for something - the WhatsApp
nudge is build order step 3 and isn't built. So the two things worth pinning
down are that it shows the right requests, and that it shows a staff member
only the villas they are actually on.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking
from apps.guests.models import Guest, GuestRequest
from apps.villas.models import Villa


@pytest.fixture
def owner_client(client, org, user, make_membership):
    make_membership(user, org, manager=True)
    client.force_login(user)
    return client


def _request_on(org, villa, guest, **kwargs):
    today = timezone.localdate()
    booking = Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=today, check_out=today + timedelta(days=3),
        source_detail=Booking.SourceDetail.MANUAL,
    )
    return GuestRequest.objects.create(
        organization=org, booking=booking, guest=guest,
        kind=kwargs.pop("kind", GuestRequest.Kind.CLEANING), **kwargs,
    )


def test_the_queue_lists_open_requests(owner_client, org, villa, guest):
    guest_request = _request_on(org, villa, guest)
    response = owner_client.get(reverse("guests:requests"))
    assert response.status_code == 200
    assert list(response.context["requests"]) == [guest_request]


def test_finished_requests_are_out_of_the_way_by_default(owner_client, org, villa, guest):
    _request_on(org, villa, guest, status=GuestRequest.Status.DONE)
    response = owner_client.get(reverse("guests:requests"))
    assert list(response.context["requests"]) == []
    assert response.context["open_count"] == 0


def test_finished_requests_can_still_be_looked_up(owner_client, org, villa, guest):
    done = _request_on(org, villa, guest, status=GuestRequest.Status.DONE)
    response = owner_client.get(reverse("guests:requests"), {"show": "all"})
    assert list(response.context["requests"]) == [done]


def test_staff_only_see_the_villas_they_are_on(client, org, user, make_membership, villa, guest):
    """A cleaner on one villa has no business reading another villa's guests."""
    other_villa = Villa.objects.create(organization=org, name="Villa Kedua", slug="kedua")
    mine = _request_on(org, villa, guest)
    _request_on(org, other_villa, guest)

    membership = make_membership(user, org, manager=False)
    membership.villas.add(villa)
    client.force_login(user)

    response = client.get(reverse("guests:requests"))
    assert list(response.context["requests"]) == [mine]


def test_another_operators_requests_never_show_up(owner_client, org, other_org, villa, guest):
    other_villa = Villa.objects.create(organization=other_org, name="Villa Ubud", slug="ubud-2")
    other_guest = Guest.objects.create(organization=other_org, full_name="Someone Else")
    _request_on(other_org, other_villa, other_guest)

    response = owner_client.get(reverse("guests:requests"))
    assert list(response.context["requests"]) == []


def test_staff_can_mark_a_request_done(owner_client, org, villa, guest):
    guest_request = _request_on(org, villa, guest)
    response = owner_client.post(
        reverse("guests:request_status", args=[guest_request.pk]),
        {"status": GuestRequest.Status.DONE}, HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    guest_request.refresh_from_db()
    assert guest_request.status == GuestRequest.Status.DONE


def test_staff_cannot_touch_a_request_on_someone_elses_villa(
    client, org, user, make_membership, villa, guest
):
    other_villa = Villa.objects.create(organization=org, name="Villa Ketiga", slug="ketiga")
    theirs = _request_on(org, other_villa, guest)

    membership = make_membership(user, org, manager=False)
    membership.villas.add(villa)
    client.force_login(user)

    response = client.post(
        reverse("guests:request_status", args=[theirs.pk]),
        {"status": GuestRequest.Status.DONE}, HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 404
    theirs.refresh_from_db()
    assert theirs.status == GuestRequest.Status.NEW


def test_a_made_up_status_is_refused(owner_client, org, villa, guest):
    guest_request = _request_on(org, villa, guest)
    response = owner_client.post(
        reverse("guests:request_status", args=[guest_request.pk]), {"status": "deleted"},
    )
    assert response.status_code == 400
    guest_request.refresh_from_db()
    assert guest_request.status == GuestRequest.Status.NEW


def test_the_page_says_nobody_is_messaged_automatically(owner_client, org, villa, guest):
    """CLAUDE.md rule 2: never let an operator assume an automatic step ran."""
    _request_on(org, villa, guest)
    response = owner_client.get(reverse("guests:requests"))
    assert b"nobody is messaged automatically yet" in response.content


def test_signed_out_visitors_are_sent_to_the_login_page(client, db):
    response = client.get(reverse("guests:requests"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# ---- the link staff paste into WhatsApp ----

def test_the_guest_link_shows_up_during_a_stay(owner_client, org, villa, guest):
    _request_on(org, villa, guest)
    response = owner_client.get(reverse("guests:detail", args=[guest.pk]))
    assert response.context["portal_link"].startswith("http")
    assert "/stay/" in response.context["portal_link"]


def test_no_guest_link_is_offered_when_it_would_not_work(owner_client, org, villa, guest):
    """Offering a link for a stay three weeks out would hand staff something
    that lands the guest on the "this link doesn't work" page.
    """
    soon = timezone.localdate() + timedelta(days=21)
    Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=soon, check_out=soon + timedelta(days=3),
        source_detail=Booking.SourceDetail.MANUAL,
    )
    response = owner_client.get(reverse("guests:detail", args=[guest.pk]))
    assert response.context["portal_link"] == ""

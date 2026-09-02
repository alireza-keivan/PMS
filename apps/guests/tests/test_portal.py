"""The guest portal at /stay/<token>/.

Two things are being tested here, and the first matters more than the second.

The door: a signed link with no password behind it is only safe because
resolve_booking refuses everything that isn't a live stay happening right now.
Each way in that should be shut gets its own test, because a regression in any
one of them quietly turns a link into a permanent one.

The page: what a guest can do once inside, and - just as important - what the
page must never show them.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking
from apps.guests.models import Guest, GuestActivity, GuestRequest
from apps.guests.portal_views import MAX_OPEN_REQUESTS
from apps.guests.tokens import make_token


def _booking(org, villa, guest, *, starts_in_days=0, nights=3, **kwargs):
    today = timezone.localdate()
    check_in = today + timedelta(days=starts_in_days)
    return Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=check_in, check_out=check_in + timedelta(days=nights),
        source_detail=Booking.SourceDetail.MANUAL,
        **kwargs,
    )


def _home_url(booking):
    return reverse("portal:home", kwargs={"token": make_token(booking)})


# ---- the door ----

def test_link_opens_during_the_stay(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1)
    response = client.get(_home_url(booking))
    assert response.status_code == 200
    assert response.context["booking"] == booking


def test_link_opens_the_day_before_check_in(client, org, villa, guest):
    """A guest reading it on the plane is the point of opening early."""
    booking = _booking(org, villa, guest, starts_in_days=1)
    assert client.get(_home_url(booking)).status_code == 200


def test_link_is_shut_two_days_before_check_in(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=2)
    assert client.get(_home_url(booking)).status_code == 404


def test_link_is_shut_after_the_stay_is_over(client, org, villa, guest):
    """The whole reason "no login" is safe: a forwarded link goes dead."""
    booking = _booking(org, villa, guest, starts_in_days=-10, nights=3)
    assert client.get(_home_url(booking)).status_code == 404


def test_link_is_shut_on_a_cancelled_booking(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1, status=Booking.Status.CANCELLED)
    assert client.get(_home_url(booking)).status_code == 404


def test_link_is_shut_on_a_calendar_only_booking(client, org, villa):
    """An iCal row carries dates and no guest, so there is nobody to let in."""
    booking = Booking.objects.create(
        organization=org, villa=villa, guest=None,
        check_in=timezone.localdate(), check_out=timezone.localdate() + timedelta(days=2),
        source_detail=Booking.SourceDetail.DATES_ONLY,
    )
    assert client.get(_home_url(booking)).status_code == 404


def test_an_edited_token_opens_nothing(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1)
    tampered = make_token(booking)[:-1] + ("x" if not make_token(booking).endswith("x") else "y")
    assert client.get(reverse("portal:home", kwargs={"token": tampered})).status_code == 404


def test_a_made_up_token_opens_nothing(client, db):
    assert client.get(reverse("portal:home", kwargs={"token": "not-a-real-token"})).status_code == 404


def test_a_link_shows_only_its_own_booking(client, org, other_org, villa, guest):
    """The signed link proves which booking someone holds. Nothing wider."""
    from apps.villas.models import Villa

    other_villa = Villa.objects.create(organization=other_org, name="Villa Ubud", slug="ubud-1")
    other_guest = Guest.objects.create(organization=other_org, full_name="Someone Else")
    _booking(other_org, other_villa, other_guest, starts_in_days=-1)

    booking = _booking(org, villa, guest, starts_in_days=-1)
    response = client.get(_home_url(booking))

    assert response.context["booking"] == booking
    assert b"Someone Else" not in response.content
    assert b"Villa Ubud" not in response.content


# ---- what the page shows ----

def test_opening_the_page_is_logged_against_the_guest(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1)
    client.get(_home_url(booking))

    activity = GuestActivity.objects.get(guest=guest, kind=GuestActivity.Kind.PORTAL_OPENED)
    assert activity.booking == booking
    assert activity.villa == villa
    assert activity.organization == org


def test_the_page_never_shows_internal_notes(client, org, villa, guest):
    guest.notes = "Complained loudly about the last villa"
    guest.save(update_fields=["notes"])
    booking = _booking(org, villa, guest, starts_in_days=-1)

    response = client.get(_home_url(booking))
    assert b"Complained loudly" not in response.content


def test_the_page_never_shows_the_rate(client, org, villa, guest):
    """What they paid and where they booked is the operator's business."""
    booking = _booking(org, villa, guest, starts_in_days=-1, nightly_rate=1500000)
    response = client.get(_home_url(booking))
    assert b"1500000" not in response.content
    assert b"1.500.000" not in response.content


# ---- asking for something ----

def _send(client, booking, **data):
    url = reverse("portal:request", kwargs={"token": make_token(booking)})
    return client.post(url, data, HTTP_HX_REQUEST="true")


def test_a_guest_can_ask_for_something(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1)
    response = _send(client, booking, kind=GuestRequest.Kind.CLEANING, message="Towels please")
    assert response.status_code == 200

    guest_request = GuestRequest.objects.get()
    assert guest_request.kind == GuestRequest.Kind.CLEANING
    assert guest_request.message == "Towels please"
    assert guest_request.booking == booking
    assert guest_request.guest == guest
    assert guest_request.organization == org
    assert guest_request.status == GuestRequest.Status.NEW


def test_nothing_claims_staff_were_messaged(client, org, villa, guest):
    """notified_at is stamped by the WhatsApp hand-off, which is build order
    step 3 and does not exist. Until it does, a request is only ever seen by
    someone opening the dashboard - and the wording has to match that.
    """
    booking = _booking(org, villa, guest, starts_in_days=-1)
    response = _send(client, booking, kind=GuestRequest.Kind.REPAIR)

    assert GuestRequest.objects.get().notified_at is None
    body = response.content.lower()
    assert b"will see" in body
    assert b"messaged" not in body
    assert b"notified" not in body


def test_a_request_is_logged_against_the_guest(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1)
    _send(client, booking, kind=GuestRequest.Kind.CHEF)

    activity = GuestActivity.objects.get(kind=GuestActivity.Kind.REQUEST_MADE)
    assert activity.guest == guest
    assert activity.booking == booking
    assert activity.subject == "Private chef"


def test_sending_nothing_is_rejected(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1)
    response = _send(client, booking, message="hello")
    assert response.status_code == 200
    assert not GuestRequest.objects.exists()
    assert b"Pick what you need first." in response.content


def test_a_message_on_its_own_is_not_required(client, org, villa, guest):
    """"Cleaning" is a complete request. Demanding a sentence loses requests."""
    booking = _booking(org, villa, guest, starts_in_days=-1)
    _send(client, booking, kind=GuestRequest.Kind.CLEANING)
    assert GuestRequest.objects.get().message == ""


def test_a_guest_cannot_bury_the_staff_list(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1)
    for _ in range(MAX_OPEN_REQUESTS):
        GuestRequest.objects.create(
            organization=org, booking=booking, guest=guest, kind=GuestRequest.Kind.CLEANING,
        )

    response = _send(client, booking, kind=GuestRequest.Kind.CLEANING)
    assert response.status_code == 200
    assert GuestRequest.objects.count() == MAX_OPEN_REQUESTS
    assert b"few requests open already" in response.content


def test_finished_requests_do_not_count_against_the_cap(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-1)
    for _ in range(MAX_OPEN_REQUESTS):
        GuestRequest.objects.create(
            organization=org, booking=booking, guest=guest,
            kind=GuestRequest.Kind.CLEANING, status=GuestRequest.Status.DONE,
        )

    _send(client, booking, kind=GuestRequest.Kind.REPAIR)
    assert GuestRequest.objects.filter(status=GuestRequest.Status.NEW).count() == 1


def test_a_shut_link_cannot_post_a_request(client, org, villa, guest):
    booking = _booking(org, villa, guest, starts_in_days=-30, nights=2)
    response = _send(client, booking, kind=GuestRequest.Kind.CLEANING)
    assert response.status_code == 404
    assert not GuestRequest.objects.exists()


def test_the_portal_works_without_javascript(client, org, villa, guest):
    """No HX-Request header: a plain form post has to work too."""
    booking = _booking(org, villa, guest, starts_in_days=-1)
    url = reverse("portal:request", kwargs={"token": make_token(booking)})

    response = client.post(url, {"kind": GuestRequest.Kind.GROCERIES})
    assert response.status_code == 302
    assert GuestRequest.objects.count() == 1

    followed = client.get(response.url)
    assert followed.status_code == 200

"""The calendar page has to work for a plain link (no JS) and for HTMX's
partial swap - both paths are exercised here, plus the no-organization state
every other screen in this app also has to handle.
"""

from datetime import date

import pytest
from django.urls import reverse



@pytest.fixture
def owner_client(client, org, user, make_membership):
    make_membership(user, org, manager=True)
    client.force_login(user)
    return client


def test_requires_login(client, db):
    response = client.get(reverse("bookings:calendar"))
    assert response.status_code == 302


def test_no_organization_shows_the_placeholder_state(client, user_without_active_organization):
    client.force_login(user_without_active_organization)
    response = client.get(reverse("bookings:calendar"))
    assert response.context["no_organization"] is True


def test_full_page_load_includes_the_page_shell(owner_client):
    response = owner_client.get(reverse("bookings:calendar"))
    assert response.status_code == 200
    assert b"<!doctype html>" in response.content  # full document, not a fragment
    assert b"calendarGrid()" in response.content   # Alpine scope wrapping the panel
    assert b'id="calendar-panel"' in response.content


def test_htmx_request_returns_only_the_panel_fragment(owner_client):
    response = owner_client.get(reverse("bookings:calendar"), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert b"<!doctype html>" not in response.content
    assert b"calendarGrid()" not in response.content  # the scope lives outside the swap
    assert b"New booking" in response.content        # but the toolbar came back


def test_default_range_is_fourteen_days(owner_client):
    response = owner_client.get(reverse("bookings:calendar"))
    assert response.context["days"] == 14


def test_invalid_days_falls_back_to_default(owner_client):
    response = owner_client.get(reverse("bookings:calendar"), {"days": "999"})
    assert response.context["days"] == 14


def test_start_date_is_parsed_from_query_param(owner_client):
    response = owner_client.get(reverse("bookings:calendar"), {"start": "2026-01-05"})
    assert response.context["start"] == date(2026, 1, 5)


def test_invalid_start_date_falls_back_to_today(owner_client):
    response = owner_client.get(reverse("bookings:calendar"), {"start": "not-a-date"})
    assert response.context["start"] == date.today()


# --- Block dates ----------------------------------------------------------
#
# A block is a Booking with status BLOCKED and no guest - the same shape an
# iCal feed writes - so these tests mostly check that nothing dresses it up as
# a real stay, and that it can never be laid over one.

@pytest.fixture
def room(org, villa):
    from apps.villas.models import Room
    return Room.objects.create(organization=org, villa=villa, name="Room 1")


def _block_post(room, first_night, free_again, **extra):
    data = {
        "villa": room.villa_id,
        "room": room.id,
        "check_in": first_night,
        "check_out": free_again,
    }
    data.update(extra)
    return data


def test_block_dates_requires_login(client, db):
    assert client.get(reverse("bookings:block")).status_code == 302


def test_block_dates_page_renders(owner_client, room):
    response = owner_client.get(reverse("bookings:block"))
    assert response.status_code == 200
    assert b"blockForm(" in response.content        # Alpine scope for the room picker
    assert room.name.encode() in response.content   # the room is offered


def test_blocking_a_room_creates_a_blocked_booking_with_no_guest(owner_client, room):
    from apps.bookings.models import Booking

    response = owner_client.post(
        reverse("bookings:block"),
        _block_post(room, "2026-10-01", "2026-10-05", reason="Pool repair"),
    )
    assert response.status_code == 302

    booking = Booking.objects.get()
    assert booking.status == Booking.Status.BLOCKED
    assert booking.source_detail == Booking.SourceDetail.MANUAL
    assert booking.guest_id is None
    assert booking.room_id == room.id
    assert booking.notes == "Pool repair"
    assert booking.check_in == date(2026, 10, 1)
    assert booking.check_out == date(2026, 10, 5)


def test_a_block_never_lands_on_top_of_a_real_booking(owner_client, org, villa, room, guest):
    from apps.bookings.models import Booking

    Booking.objects.create(
        organization=org, villa=villa, room=room, guest=guest,
        check_in=date(2026, 10, 3), check_out=date(2026, 10, 8),
    )
    response = owner_client.post(
        reverse("bookings:block"), _block_post(room, "2026-10-01", "2026-10-05"),
    )
    assert response.status_code == 200  # form re-rendered, nothing written
    assert Booking.objects.filter(status=Booking.Status.BLOCKED).count() == 0


def test_free_again_date_has_to_be_after_the_first_night(owner_client, room):
    from apps.bookings.models import Booking

    response = owner_client.post(
        reverse("bookings:block"), _block_post(room, "2026-10-05", "2026-10-05"),
    )
    assert response.status_code == 200
    assert "check_out" in response.context["form"].errors
    assert Booking.objects.count() == 0


def test_cannot_block_a_room_in_someone_elses_organization(owner_client, other_org):
    from apps.bookings.models import Booking
    from apps.villas.models import Room, Villa

    their_villa = Villa.objects.create(organization=other_org, name="Their Villa", slug="theirs")
    their_room = Room.objects.create(organization=other_org, villa=their_villa, name="Room 1")

    response = owner_client.post(
        reverse("bookings:block"), _block_post(their_room, "2026-10-01", "2026-10-05"),
    )
    assert response.status_code == 200
    assert response.context["form"].errors
    assert Booking.objects.count() == 0


def test_a_block_shows_on_the_calendar_as_not_available(owner_client, org, villa, room):
    from apps.bookings.models import Booking

    Booking.objects.create(
        organization=org, villa=villa, room=room, guest=None,
        check_in=date(2026, 10, 1), check_out=date(2026, 10, 5),
        status=Booking.Status.BLOCKED, source_detail=Booking.SourceDetail.MANUAL,
        notes="Pool repair",
    )
    response = owner_client.get(reverse("bookings:calendar"), {"start": "2026-10-01"})
    bars = [
        bar
        for row in response.context["rows"] if row["kind"] == "room"
        for bar in row["bars"]
    ]
    assert len(bars) == 1
    assert bars[0]["status"] == "blocked"
    assert bars[0]["is_block"] is True
    assert bars[0]["reason"] == "Pool repair"
    assert bars[0]["label"] != "Booked"  # never dressed up as a real stay

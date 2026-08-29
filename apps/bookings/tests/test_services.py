"""calendar_status() decides a bar's single color - getting the payment-owed
override wrong would put a bar in front of staff that quietly hides the one
thing that actually needs attention. build_calendar_data() is the query that
backs both the page and the JSON endpoint, so its villa-scoping and search
behaviour matter regardless of which caller hits it.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from apps.bookings.models import Booking, BookingPayment
from apps.bookings.services import build_calendar_data, build_calendar_rows, calendar_status
from apps.guests.services import find_or_create_guest
from apps.organizations.models import Membership


def _dates(today, nights=3, offset=0):
    start = today + timedelta(days=offset)
    return start, start + timedelta(days=nights)


def _booking(org, villa, today, offset, nights=3, **kwargs):
    check_in, check_out = _dates(today, nights=nights, offset=offset)
    return Booking.objects.create(
        organization=org, villa=villa, check_in=check_in, check_out=check_out, **kwargs
    )


def test_blocked_booking_is_always_blocked_regardless_of_dates_or_money(org, villa):
    today = date.today()
    booking = _booking(org, villa, today, offset=-1, status=Booking.Status.BLOCKED)
    assert calendar_status(booking, today, Decimal("0")) == "blocked"


def test_money_owed_overrides_stay_stage_color(org, villa):
    today = date.today()
    booking = _booking(org, villa, today, offset=0, nights=3)  # currently checked in
    assert calendar_status(booking, today, Decimal("500000")) == "payment_incomplete"


def test_upcoming_stay_with_nothing_owed_is_confirmed(org, villa):
    today = date.today()
    booking = _booking(org, villa, today, offset=5)
    assert calendar_status(booking, today, Decimal("0")) == "confirmed"


def test_stay_in_progress_with_nothing_owed_is_checked_in(org, villa):
    today = date.today()
    booking = _booking(org, villa, today, offset=-1, nights=3)
    assert calendar_status(booking, today, Decimal("0")) == "checked_in"


def test_finished_stay_with_nothing_owed_is_checked_out(org, villa):
    today = date.today()
    booking = _booking(org, villa, today, offset=-10, nights=3)
    assert calendar_status(booking, today, Decimal("0")) == "checked_out"


@pytest.fixture
def owner_request(org, user, villa):
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OWNER)
    request = RequestFactory().get("/bookings/calendar/")
    request.organization = org
    request.user = user
    return request


def test_every_active_villa_gets_a_group_even_with_no_bookings(owner_request, org):
    from apps.villas.models import Villa

    Villa.objects.create(organization=org, name="Villa Empty", slug="villa-empty", area="Ubud")
    data = build_calendar_data(owner_request, start=date.today(), days=14, q="")
    group_labels = [g["content"] for g in data["groups"]]
    assert any("Villa Empty" in label for label in group_labels)
    assert data["items"] == []


def test_inactive_villas_are_excluded(owner_request, org, villa):
    from apps.villas.models import Villa

    Villa.objects.create(organization=org, name="Retired Villa", slug="retired", is_active=False)
    data = build_calendar_data(owner_request, start=date.today(), days=14, q="")
    group_labels = [g["content"] for g in data["groups"]]
    assert not any("Retired Villa" in label for label in group_labels)


def test_staff_scoped_to_specific_villas_only_sees_those(org, user, villa):
    from apps.villas.models import Villa

    Villa.objects.create(organization=org, name="Not Assigned", slug="not-assigned")
    membership = Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)
    membership.villas.add(villa)

    request = RequestFactory().get("/bookings/calendar/")
    request.organization = org
    request.user = user

    data = build_calendar_data(request, start=date.today(), days=14, q="")
    group_labels = [g["content"] for g in data["groups"]]
    assert not any("Not Assigned" in label for label in group_labels)
    assert any(villa.name in label for label in group_labels)


def test_staff_with_no_assigned_villas_sees_every_villa(org, user, villa):
    from apps.villas.models import Villa

    other_villa = Villa.objects.create(organization=org, name="Also Mine", slug="also-mine")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)

    request = RequestFactory().get("/bookings/calendar/")
    request.organization = org
    request.user = user

    data = build_calendar_data(request, start=date.today(), days=14, q="")
    group_labels = [g["content"] for g in data["groups"]]
    assert any(other_villa.name in label for label in group_labels)


def test_search_by_guest_name_keeps_the_whole_villa_row(owner_request, org, villa):
    today = date.today()
    guest = find_or_create_guest(org, full_name="Anna Petrova")
    _booking(org, villa, today, offset=0, guest=guest, source_detail=Booking.SourceDetail.FULL)
    _booking(org, villa, today, offset=1, nights=1)  # unrelated booking, same villa

    data = build_calendar_data(owner_request, start=today, days=14, q="Anna")
    assert len(data["items"]) == 2  # both bookings on the matched villa render


def test_search_with_no_match_hides_the_villa_row(owner_request, org, villa):
    data = build_calendar_data(owner_request, start=date.today(), days=14, q="Nobody Here")
    assert data["groups"] == []
    assert data["items"] == []


def test_amount_owed_is_hidden_from_staff(org, user, villa):
    today = date.today()
    booking = _booking(org, villa, today, offset=0)
    BookingPayment.objects.create(
        organization=org, booking=booking, amount="1000000", currency="IDR", is_outstanding=True,
    )
    Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)
    request = RequestFactory().get("/bookings/calendar/")
    request.organization = org
    request.user = user

    data = build_calendar_data(request, start=today, days=14, q="")
    item = data["items"][0]
    assert item["can_see_money"] is False
    assert item["amount_owed"] is None
    # Staff still needs to know the stay is flagged, even without the figure.
    assert "cal-status-payment_incomplete" in item["className"]


def test_amount_owed_is_visible_to_owners(owner_request, org, villa):
    today = date.today()
    booking = _booking(org, villa, today, offset=0)
    BookingPayment.objects.create(
        organization=org, booking=booking, amount="1000000", currency="IDR", is_outstanding=True,
    )
    data = build_calendar_data(owner_request, start=today, days=14, q="")
    item = data["items"][0]
    assert item["can_see_money"] is True
    assert item["amount_owed"] == "1000000.00"


def _group_by_id(data, group_id):
    return next(g for g in data["groups"] if g["id"] == group_id)


def test_villa_nests_its_rooms_as_groups(owner_request, org, villa):
    from apps.villas.models import Room

    extra = Room.objects.create(organization=org, villa=villa, name="Room 2")
    default_room = villa.rooms.get(name="Standard")  # created with the villa

    data = build_calendar_data(owner_request, start=date.today(), days=14, q="")
    villa_group = _group_by_id(data, f"villa-{villa.id}")
    assert villa_group["nestedGroups"] == [f"room-{default_room.id}", f"room-{extra.id}"]
    assert _group_by_id(data, f"room-{extra.id}")["content"] == "Room 2"


def test_booking_assigned_to_a_room_groups_under_that_room(owner_request, org, villa):
    from apps.villas.models import Room

    room = Room.objects.create(organization=org, villa=villa, name="Room 1")
    today = date.today()
    booking = _booking(org, villa, today, offset=0, room=room)
    data = build_calendar_data(owner_request, start=today, days=14, q="")
    item = data["items"][0]
    assert item["group"] == f"room-{room.id}"
    assert item["room_display"] == "Room 1"
    assert booking.villa_id == villa.id  # sanity: villa untouched by the room assignment


def test_roomless_booking_on_a_villa_with_rooms_gets_the_unassigned_bucket(owner_request, org, villa):
    from apps.villas.models import Room

    Room.objects.create(organization=org, villa=villa, name="Room 1")
    today = date.today()
    _booking(org, villa, today, offset=0)  # no room set

    data = build_calendar_data(owner_request, start=today, days=14, q="")
    unassigned_id = f"room-none-{villa.id}"
    assert data["items"][0]["group"] == unassigned_id
    assert data["items"][0]["room_display"] is None
    assert _group_by_id(data, unassigned_id)["content"] == "Unassigned"


def test_unassigned_bucket_is_absent_when_every_booking_has_a_room(owner_request, org, villa):
    from apps.villas.models import Room

    room = Room.objects.create(organization=org, villa=villa, name="Room 1")
    _booking(org, villa, date.today(), offset=0, room=room)

    data = build_calendar_data(owner_request, start=date.today(), days=14, q="")
    group_ids = [g["id"] for g in data["groups"]]
    assert f"room-none-{villa.id}" not in group_ids


def test_a_room_from_another_villa_is_rejected_on_the_booking(org, villa, other_org):
    from apps.villas.models import Room, Villa

    other_villa = Villa.objects.create(organization=org, name="Other", slug="other")
    room = Room.objects.create(organization=org, villa=other_villa, name="Room 1")
    today = date.today()
    booking = Booking(
        organization=org, villa=villa, room=room,
        check_in=today, check_out=today + timedelta(days=2),
    )
    with pytest.raises(ValidationError):
        booking.full_clean()


# --- build_calendar_rows: the server-rendered grid ------------------------


def _rows_of_kind(data, kind):
    return [r for r in data["rows"] if r["kind"] == kind]


def test_rows_emit_one_day_column_per_day_and_mark_today(owner_request, villa):
    today = date.today()
    data = build_calendar_rows(owner_request, start=today, days=7, q="")
    assert len(data["day_columns"]) == 7
    assert [c["is_today"] for c in data["day_columns"]] == [True, False, False, False, False, False, False]


def test_rows_are_ordered_area_then_villa_then_its_rooms(owner_request, org, villa):
    villa.area = "Canggu"
    villa.save(update_fields=["area"])
    data = build_calendar_rows(owner_request, start=date.today(), days=14, q="")
    kinds = [r["kind"] for r in data["rows"]]
    assert kinds == ["area", "villa", "room", "add_room"]
    assert _rows_of_kind(data, "area")[0]["label"] == "Canggu"
    assert _rows_of_kind(data, "room")[0]["villa_id"] == villa.id


def test_a_booking_becomes_a_bar_on_its_own_room_row(owner_request, org, villa):
    today = date.today()
    room = villa.rooms.get(name="Standard")
    guest = find_or_create_guest(org, full_name="Anna Petrova")
    _booking(org, villa, today, offset=0, room=room, guest=guest,
             source_detail=Booking.SourceDetail.FULL)

    data = build_calendar_rows(owner_request, start=today, days=14, q="")
    bars = _rows_of_kind(data, "room")[0]["bars"]
    assert [b["label"] for b in bars] == ["Anna Petrova"]
    assert bars[0]["room_name"] == "Standard"


def test_a_bar_is_positioned_by_its_offset_into_the_window(owner_request, org, villa):
    today = date.today()
    room = villa.rooms.get(name="Standard")
    _booking(org, villa, today, offset=2, nights=2, room=room)  # days 2-3 of 10

    bar = _rows_of_kind(build_calendar_rows(owner_request, start=today, days=10, q=""), "room")[0]["bars"][0]
    assert "left:calc(20.0000%" in bar["style"]
    assert "width:calc(20.0000%" in bar["style"]


def test_a_stay_starting_before_the_window_is_clamped_to_its_left_edge(owner_request, org, villa):
    today = date.today()
    room = villa.rooms.get(name="Standard")
    _booking(org, villa, today, offset=-5, nights=8, room=room)  # started 5 days ago

    bar = _rows_of_kind(build_calendar_rows(owner_request, start=today, days=10, q=""), "room")[0]["bars"][0]
    assert "left:calc(0.0000%" in bar["style"]
    assert "width:calc(30.0000%" in bar["style"]  # 3 of its 8 nights are still visible


def test_money_owed_is_withheld_from_staff_in_the_rows(org, user, villa):
    today = date.today()
    room = villa.rooms.get(name="Standard")
    booking = _booking(org, villa, today, offset=0, room=room)
    BookingPayment.objects.create(
        organization=org, booking=booking, amount="1000000", currency="IDR", is_outstanding=True,
    )
    Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)
    request = RequestFactory().get("/bookings/calendar/")
    request.organization = org
    request.user = user

    bar = _rows_of_kind(build_calendar_rows(request, start=today, days=14, q=""), "room")[0]["bars"][0]
    assert bar["can_see_money"] is False
    assert bar["amount_owed"] is None
    # The flag itself still has to reach staff, just not the figure.
    assert bar["status"] == "payment_incomplete"

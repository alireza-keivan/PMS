"""Sliding upcoming bookings together so a longer stay fits.

The case that made this necessary: three rooms of one type, each holding a
short stay in a different part of the same week. Nothing is free for the whole
week, even though all three short stays would fit in one room. See
apps.bookings.services.plan_room_moves.
"""

from datetime import date

import pytest

from apps.bookings.models import Booking
from apps.bookings.services import apply_room_moves, find_available_room, plan_room_moves
from apps.villas.models import Room, RoomCategory

TODAY = date(2026, 8, 25)  # a week before the September dates below


def _d(day):
    return date(2026, 9, day)


@pytest.fixture
def category(org, villa):
    villa.auto_reassign_rooms = True
    villa.save(update_fields=["auto_reassign_rooms"])
    return RoomCategory.objects.create(organization=org, villa=villa, name="Deluxe")


@pytest.fixture
def rooms(org, villa, category):
    return [
        Room.objects.create(organization=org, villa=villa, category=category, name=f"Deluxe {n}")
        for n in (1, 2, 3)
    ]


def _book(org, villa, room, first, last, **kwargs):
    return Booking.objects.create(
        organization=org, villa=villa, room=room,
        check_in=_d(first), check_out=_d(last), **kwargs
    )


def _fragment(org, villa, rooms):
    """The exact situation from the report: 1-3, 3-5, 5-7, one room each."""
    return [
        _book(org, villa, rooms[0], 1, 3),
        _book(org, villa, rooms[1], 3, 5),
        _book(org, villa, rooms[2], 5, 7),
    ]


def test_long_stay_fits_once_short_ones_are_slid_together(org, villa, rooms):
    _fragment(org, villa, rooms)

    room, moves = plan_room_moves(rooms[0].category, _d(1), _d(7), today=TODAY)

    assert room is not None
    apply_room_moves(moves)

    # Whatever the packer chose, the room it handed back has to be genuinely
    # empty for the whole week once the moves are written.
    clash = Booking.objects.filter(room=room, check_in__lt=_d(7), check_out__gt=_d(1))
    assert not clash.exists()
    # And nobody was moved to another room type or another villa.
    for booking in Booking.objects.all():
        assert booking.room.category_id == rooms[0].category_id


def test_it_moves_as_few_bookings_as_it_can(org, villa, rooms):
    _fragment(org, villa, rooms)

    _room, moves = plan_room_moves(rooms[0].category, _d(1), _d(7), today=TODAY)

    # Three stays that all fit in one room, one of which is already in the
    # room that ends up free - so at most two people hear "different room".
    assert len(moves) <= 2


def test_nothing_moves_when_a_room_is_already_free(org, villa, rooms):
    _book(org, villa, rooms[0], 1, 3)

    room, next_free, moves = find_available_room(rooms[0].category, _d(1), _d(7))

    assert room in (rooms[1], rooms[2])
    assert next_free is None
    assert moves == []


def test_switched_off_villa_is_told_it_is_full(org, villa, rooms):
    villa.auto_reassign_rooms = False
    villa.save(update_fields=["auto_reassign_rooms"])
    _fragment(org, villa, rooms)

    room, next_free, moves = find_available_room(rooms[0].category, _d(1), _d(7))

    assert room is None
    assert moves == []
    assert next_free == _d(3)  # the soonest anything opens up


def test_a_stay_already_under_way_is_never_moved(org, villa, rooms):
    """A guest in the room tonight keeps their room number, even if moving
    them would have made the new booking fit."""
    staying = _book(org, villa, rooms[0], 1, 3)
    _book(org, villa, rooms[1], 3, 5)
    _book(org, villa, rooms[2], 5, 7)

    # "Today" is the 2nd - that first stay is under way, so room 1 is pinned
    # across the 1st-3rd and can never be the room handed back. The other two
    # stays are still free to slide, so the week does open up elsewhere.
    room, moves = plan_room_moves(rooms[0].category, _d(1), _d(7), today=_d(2))

    assert room is not None
    assert room != rooms[0]
    assert staying.pk not in {m[0] for m in moves}
    staying.refresh_from_db()
    assert staying.room_id == rooms[0].id


def test_cancelled_bookings_are_not_in_the_way(org, villa, rooms):
    _book(org, villa, rooms[0], 1, 7, status=Booking.Status.CANCELLED)
    _book(org, villa, rooms[1], 1, 7)
    _book(org, villa, rooms[2], 1, 7)

    room, moves = plan_room_moves(rooms[0].category, _d(1), _d(7), today=TODAY)

    assert room == rooms[0]
    assert moves == []


def test_genuinely_full_room_type_stays_full(org, villa, rooms):
    """Three rooms all booked across the whole week really is full - no amount
    of shuffling invents a fourth room."""
    for room in rooms:
        _book(org, villa, room, 1, 7)

    room, next_free, moves = find_available_room(rooms[0].category, _d(1), _d(7))

    assert room is None
    assert moves == []
    assert next_free == _d(7)


def test_blocked_rooms_are_respected(org, villa, rooms):
    """A room switched off for maintenance is not somewhere to put people."""
    _fragment(org, villa, rooms)
    rooms[2].is_active = False
    rooms[2].save(update_fields=["is_active"])

    room, moves = plan_room_moves(rooms[0].category, _d(1), _d(7), today=TODAY)

    assert room is not None
    assert room.is_active
    apply_room_moves(moves)
    assert not Booking.objects.filter(
        room=room, check_in__lt=_d(7), check_out__gt=_d(1)
    ).exists()


def test_back_to_back_stays_do_not_count_as_overlapping(org, villa, rooms):
    """Checking out on the 3rd and in on the 3rd is one room, not two."""
    _book(org, villa, rooms[0], 1, 3)
    _book(org, villa, rooms[1], 3, 5)
    _book(org, villa, rooms[2], 1, 7)

    room, moves = plan_room_moves(rooms[0].category, _d(3), _d(5), today=TODAY)

    assert room is not None


def test_another_organizations_bookings_are_never_touched(org, other_org, villa, rooms):
    _fragment(org, villa, rooms)
    outsider = Booking.objects.create(
        organization=other_org, villa=villa, room=rooms[0],
        check_in=_d(1), check_out=_d(7),
    )

    _room, moves = plan_room_moves(rooms[0].category, _d(1), _d(7), today=TODAY)

    assert outsider.pk not in {m[0] for m in moves}

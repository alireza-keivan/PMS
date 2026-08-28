"""calendar_status() decides a bar's single color - getting the payment-owed
override wrong would put a bar in front of staff that quietly hides the one
thing that actually needs attention. build_calendar_data() is the query that
backs both the page and the JSON endpoint, so its villa-scoping and search
behaviour matter regardless of which caller hits it.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import RequestFactory

from apps.bookings.models import Booking, BookingPayment
from apps.bookings.services import build_calendar_data, calendar_status
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

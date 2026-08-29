"""The one session-authenticated route on the otherwise webhook-only Ninja
API - see config/api.py's docstring.

The calendar page itself does NOT use this: it renders its grid server-side
and refreshes over HTMX. This endpoint stays for scripted/external callers
that want the same range of bookings as JSON, in a flat groups+items shape
(area -> villa -> room).
"""

from datetime import date

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from apps.bookings.services import build_calendar_data

router = Router(tags=["bookings"])

VALID_RANGE_SIZES = (7, 14, 30)
DEFAULT_RANGE_SIZE = 14


class GroupOut(Schema):
    id: str
    content: str
    nestedGroups: list[str] | None = None


class ItemOut(Schema):
    id: int
    group: str
    start: str
    end: str
    content: str
    className: str
    title: str
    type: str
    guest_count: int
    channel_display: str
    status_display: str
    has_guest_details: bool
    can_see_money: bool
    reference: str
    villa_name: str
    room_display: str | None = None
    total_amount: str | None = None
    amount_owed: str | None = None
    currency: str | None = None


class CalendarDataOut(Schema):
    groups: list[GroupOut]
    items: list[ItemOut]


@router.get("/calendar/", response=CalendarDataOut, auth=django_auth)
def calendar_data(request, start: date | None = None, days: int = DEFAULT_RANGE_SIZE, q: str = ""):
    if request.organization is None:
        raise HttpError(403, "No organization")
    range_days = days if days in VALID_RANGE_SIZES else DEFAULT_RANGE_SIZE
    return build_calendar_data(
        request,
        start=start or timezone.localdate(),
        days=range_days,
        q=q.strip(),
    )

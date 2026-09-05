"""The /reporting page - earnings, occupancy, channels and guest origins.

Everything on this screen is computed from the database at request time; there
are no sample numbers anywhere. Where a figure genuinely cannot be known - a
payment with no exchange rate on file, a calendar-feed booking that carries no
price - it is left out of the total and counted separately, so a number on
screen is never quietly short. Same rule as apps/reporting/fx.py.

Two money figures are shown side by side, and they mean different things:

  money received  - BookingPayment rows already in, bucketed by the day the
                    money arrived. This is the headline.
  booking value   - nightly_rate x nights for confirmed stays, bucketed by
                    check-in. Includes stays not yet paid for, and is blank on
                    bookings whose price we never got (iCal feeds).
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from apps.bookings.models import Booking, BookingPayment
from apps.guests.constants import NATIONALITY_CHOICES
from apps.reporting.fx import convert
from apps.villas.models import Room

logger = logging.getLogger(__name__)

OCCUPYING_STATUSES = [Booking.Status.CONFIRMED, Booking.Status.BLOCKED]

RANGE_CHOICES = [
    ("this_month", _("This month")),
    ("last_month", _("Last month")),
    ("last_3", _("Last 3 months")),
    ("this_year", _("This year")),
]
DEFAULT_RANGE = "this_month"

# "What's already booked ahead" - always counted forward from today, never
# from the chosen range. Widest window last; the view sizes its one query off
# the largest entry here.
AHEAD_WINDOWS = [
    (30, _("Next 30 days")),
    (60, _("Next 60 days")),
    (90, _("Next 90 days")),
]

# How many months the two trend charts draw, ending with the chosen period's
# last month. Fixed rather than "one bar per month in the range" so that
# picking "This month" doesn't collapse the chart into a single bar.
TREND_MONTHS = 6

NATIONALITY_LABELS = dict(NATIONALITY_CHOICES)

# Chart geometry, matching the design's 640x200 viewBox.
CHART_W, CHART_H, CHART_PAD, BAR_GAP = 640, 200, 20, 14

CHANNEL_COLORS = {
    Booking.Channel.AIRBNB: "#d67f48",
    Booking.Channel.BOOKING_COM: "#8fa073",
    Booking.Channel.DIRECT: "#56633f",
    Booking.Channel.WHATSAPP: "#b2622d",
    Booking.Channel.WALK_IN: "#728157",
    Booking.Channel.OTHER: "#c0b6a5",
}
BAR_COLOR = "#d67f48"
LINE_COLOR = "#728157"
NATIONALITY_COLOR = "#d67f48"
OTHER_COLOR = "#c0b6a5"


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> "Period":
        length = timedelta(days=self.days)
        return Period(self.start - length, self.start - timedelta(days=1))


def month_start(day: date) -> date:
    return day.replace(day=1)


def add_months(day: date, months: int) -> date:
    """First day of the month `months` away from `day`'s month."""
    index = (day.year * 12 + day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def resolve_period(range_key: str, today: date) -> Period:
    """Turn the picker's choice into real dates. Unknown keys fall back to
    this month rather than erroring - the value comes from a query string."""
    if range_key == "last_month":
        start = add_months(month_start(today), -1)
        return Period(start, add_months(start, 1) - timedelta(days=1))
    if range_key == "last_3":
        return Period(add_months(month_start(today), -2), today)
    if range_key == "this_year":
        return Period(date(today.year, 1, 1), today)
    return Period(month_start(today), today)


def overlap_nights(booking, start: date, end: date) -> int:
    """Nights of this stay that fall inside [start, end] inclusive."""
    first = max(booking.check_in, start)
    last = min(booking.check_out, end + timedelta(days=1))
    return max((last - first).days, 0)


class ReportData:
    """Pulls one org's numbers for one period. Built per request."""

    def __init__(self, organization, villas, period: Period):
        self.org = organization
        self.villas = list(villas)
        self.villa_ids = [v.id for v in self.villas]
        self.period = period
        self.currency = organization.default_currency
        self.unconverted_payments = 0
        self.bookings_without_price = 0
        # units per villa: individually bookable rooms, or the villa itself
        # when none are set up yet.
        counts = defaultdict(int)
        for villa_id in Room.objects.filter(
            villa_id__in=self.villa_ids, is_active=True
        ).values_list("villa_id", flat=True):
            counts[villa_id] += 1
        self.units = {v.id: counts.get(v.id, 0) or 1 for v in self.villas}

    # -- money received ---------------------------------------------------

    def payments(self, start: date, end: date):
        return BookingPayment.objects.filter(
            organization=self.org,
            is_outstanding=False,
            received_on__gte=start,
            received_on__lte=end,
            booking__villa_id__in=self.villa_ids,
        ).values_list("amount", "currency", "received_on", "booking__villa_id")

    def received(self, start: date, end: date, count_gaps: bool = True):
        """(total, per-villa totals). Rows with no exchange rate are skipped."""
        total = Decimal("0")
        per_villa = defaultdict(Decimal)
        for amount, currency, received_on, villa_id in self.payments(start, end):
            converted = convert(amount, currency, self.currency, received_on)
            if converted is None:
                if count_gaps:
                    self.unconverted_payments += 1
                continue
            total += converted
            per_villa[villa_id] += converted
        return total, per_villa

    # -- booking value ----------------------------------------------------

    def bookings(self, start: date, end: date):
        """Confirmed stays touching the window, newest first is irrelevant here."""
        return Booking.objects.filter(
            organization=self.org,
            villa_id__in=self.villa_ids,
            status=Booking.Status.CONFIRMED,
            check_in__lte=end,
            check_out__gt=start,
        )

    def booking_value(self, start: date, end: date, count_gaps: bool = True):
        """(total, per-villa) value of stays *starting* in the window.

        Bucketed by check-in, not spread across nights: an owner reads "this
        booking was worth X" as belonging to the day it started.
        """
        total = Decimal("0")
        per_villa = defaultdict(Decimal)
        rows = Booking.objects.filter(
            organization=self.org,
            villa_id__in=self.villa_ids,
            status=Booking.Status.CONFIRMED,
            check_in__gte=start,
            check_in__lte=end,
        ).values_list("nightly_rate", "check_in", "check_out", "villa_id")
        for rate, check_in, check_out, villa_id in rows:
            if not rate:
                if count_gaps:
                    self.bookings_without_price += 1
                continue
            value = Decimal(rate) * (check_out - check_in).days
            total += value
            per_villa[villa_id] += value
        return total, per_villa

    # -- occupancy --------------------------------------------------------

    def occupancy(self, start: date, end: date):
        """(percent, booked nights, available nights, per-villa percent)."""
        nights = (end - start).days + 1
        available = {v.id: self.units[v.id] * nights for v in self.villas}
        booked = defaultdict(int)
        rows = Booking.objects.filter(
            organization=self.org,
            villa_id__in=self.villa_ids,
            status__in=OCCUPYING_STATUSES,
            check_in__lte=end,
            check_out__gt=start,
        ).values_list("villa_id", "room_id", "check_in", "check_out")
        for villa_id, room_id, check_in, check_out in rows:
            first = max(check_in, start)
            last = min(check_out, end + timedelta(days=1))
            spanned = max((last - first).days, 0)
            # A booking with no room named takes the whole villa - that is what
            # a calendar-feed block actually means.
            booked[villa_id] += spanned * (1 if room_id else self.units[villa_id])
        total_booked = 0
        total_available = 0
        per_villa = {}
        for villa in self.villas:
            got = min(booked.get(villa.id, 0), available[villa.id])
            total_booked += got
            total_available += available[villa.id]
            per_villa[villa.id] = percent(got, available[villa.id])
        return percent(total_booked, total_available), total_booked, total_available, per_villa

    def avg_nightly(self, start: date, end: date):
        """Average agreed price per booked night, from the stays that have one."""
        paid_nights = 0
        weighted = Decimal("0")
        per_villa_nights = defaultdict(int)
        per_villa_value = defaultdict(Decimal)
        rows = self.bookings(start, end).values_list(
            "nightly_rate", "check_in", "check_out", "villa_id"
        )
        for rate, check_in, check_out, villa_id in rows:
            if not rate:
                continue
            first = max(check_in, start)
            last = min(check_out, end + timedelta(days=1))
            spanned = max((last - first).days, 0)
            if not spanned:
                continue
            paid_nights += spanned
            weighted += Decimal(rate) * spanned
            per_villa_nights[villa_id] += spanned
            per_villa_value[villa_id] += Decimal(rate) * spanned
        average = weighted / paid_nights if paid_nights else None
        per_villa = {
            villa_id: per_villa_value[villa_id] / nights
            for villa_id, nights in per_villa_nights.items()
            if nights
        }
        return average, per_villa


def percent(part, whole) -> int:
    return round(part / whole * 100) if whole else 0


def change(now, before):
    """Percent movement between two periods, or None when there is nothing to
    compare against. Never fabricates a '+100%' out of a zero baseline."""
    if before in (None, 0) or now is None:
        return None
    return float((Decimal(now) - Decimal(before)) / Decimal(before) * 100)

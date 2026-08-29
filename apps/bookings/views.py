"""Booking calendar - the main screen of the dashboard. Read-only for now -
see CLAUDE.md rule 5 (never write to live booking data without confirmation).
"""

from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import TemplateView

from apps.bookings.services import (
    CALENDAR_STATUS_LABELS,
    STATUS_BAR_STYLE,
    build_calendar_rows,
)

VALID_RANGE_SIZES = [7, 14, 30]
DEFAULT_RANGE_SIZE = 14


class CalendarView(LoginRequiredMixin, TemplateView):
    template_name = "bookings/calendar.html"

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        template = "bookings/_calendar_panel.html" if request.htmx else self.template_name
        return render(request, template, context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        if org is None:
            context["no_organization"] = True
            return context

        today = timezone.localdate()
        start = _parse_date(self.request.GET.get("start")) or today
        days = _parse_days(self.request.GET.get("days"))
        q = self.request.GET.get("q", "").strip()

        data = build_calendar_rows(self.request, start=start, days=days, q=q)

        context.update(
            day_columns=data["day_columns"],
            rows=data["rows"],
            start=start,
            days=days,
            q=q,
            today=today,
            range_end=start + timedelta(days=days - 1),
            range_size_tabs=[
                {"label": str(n), "href": _tab_href(self.request, days=n), "active": n == days}
                for n in VALID_RANGE_SIZES
            ],
            nav=_nav_hrefs(self.request, start, days),
            legend=[
                {"key": key, "label": label, "style": STATUS_BAR_STYLE[key]}
                for key, label in CALENDAR_STATUS_LABELS.items()
            ],
        )
        return context


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_days(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RANGE_SIZE
    return n if n in VALID_RANGE_SIZES else DEFAULT_RANGE_SIZE


def _tab_href(request, **overrides) -> str:
    """Same small pattern as apps/messaging/views.py::_tab_href - current
    query string with the given params replaced, so switching one control
    (range size, date, search) never resets the others.
    """
    params = request.GET.copy()
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    query = params.urlencode()
    return f"?{query}" if query else "?"


def _nav_hrefs(request, start, days) -> dict:
    return {
        "today": _tab_href(request, start=None),
        "day_back": _tab_href(request, start=(start - timedelta(days=1)).isoformat()),
        "day_forward": _tab_href(request, start=(start + timedelta(days=1)).isoformat()),
        "range_back": _tab_href(request, start=(start - timedelta(days=days)).isoformat()),
        "range_forward": _tab_href(request, start=(start + timedelta(days=days)).isoformat()),
    }

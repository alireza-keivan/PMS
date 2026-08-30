"""Booking calendar - the main screen of the dashboard.

Reading was the only thing this file did for a long time - see CLAUDE.md rule
5 (never write to live booking data without confirmation). BookingRemoveView
and BookingRescheduleView are the first writes: both sit behind a confirm
step in the calendar's own UI (static/js/calendar.js's confirmTarget), and
both re-check everything server-side rather than trusting what the client
proposed - the confirm dialog's text is a preview, not the source of truth.
"""

import logging
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, View

from apps.bookings.forms import ReservationForm
from apps.bookings.models import Booking, BookingPayment
from apps.bookings.services import (
    CALENDAR_STATUS_LABELS,
    STATUS_BAR_STYLE,
    build_calendar_rows,
    find_available_room,
    scoped_villas,
)
from apps.core.utils import safe_next
from apps.guests.services import find_or_create_guest
from apps.villas.models import Room, RoomCategory

logger = logging.getLogger(__name__)

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


class ReservationCreateView(LoginRequiredMixin, View):
    """Add Reservation - a booking entered by hand (walk-ins, phone calls,
    WhatsApp conversations not yet on Beds24). Villa/room-type/date-clash
    checks always re-run server-side on submit through ReservationForm.clean()
    - see ReservationAvailabilityView below for the live version of the same
    check, which is a preview only and never trusted at save time.

    Saves and redirects back to itself (not to the calendar) so a blank form
    is what staff see next - the common case is adding several reservations
    in a row, e.g. after a call with an OTA or a stack of WhatsApp bookings.
    """

    template_name = "bookings/add.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)  # LoginRequiredMixin handles it
        if request.organization is None:
            return redirect("bookings:calendar")
        self.villas, self.membership = scoped_villas(request)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = ReservationForm(villas=self.villas, hide_money=not self.membership.can_see_money)
        return self._render(form)

    def post(self, request):
        form = ReservationForm(
            request.POST, villas=self.villas, hide_money=not self.membership.can_see_money,
        )
        if not form.is_valid():
            return self._render(form)

        data = form.cleaned_data
        org = request.organization
        with transaction.atomic():
            guest = find_or_create_guest(
                org, full_name=data["full_name"], email=data.get("email", ""),
                phone=data.get("phone", ""), nationality=data.get("nationality", ""),
            )
            # find_or_create_guest already fills gaps on email/phone/nationality
            # without overwriting what's on file - language isn't one of the
            # fields it knows about, so the same "don't overwrite" rule is
            # applied here by hand.
            if data.get("language") and not guest.preferred_language:
                guest.preferred_language = data["language"]
                guest.save(update_fields=["preferred_language"])

            booking = Booking.objects.create(
                organization=org, villa=data["villa"], room=form.available_room, guest=guest,
                check_in=data["check_in"], check_out=data["check_out"],
                guest_count=data["guest_count"], channel=data["booked_through"],
                status=data["status"], source_detail=Booking.SourceDetail.MANUAL,
                nightly_rate=data.get("nightly_rate"), notes=data.get("notes", ""),
            )
            self._record_payments(org, booking, data)

        logger.info(
            "Reservation %s created for villa %s (%s), room %s, %s to %s - guest %s, by user %s",
            booking.pk, booking.villa_id, booking.villa.name, booking.room_id,
            booking.check_in, booking.check_out, guest.pk, request.user.pk,
        )
        messages.success(request, _("Reservation saved."))
        redirect_url = reverse("bookings:add")
        if not guest.nationality:
            redirect_url += "?nationality_pending=1"
        return redirect(redirect_url)

    def _record_payments(self, org, booking, data):
        """One payment row for what's been paid, one for what's still owed -
        matches how apps.bookings.services.payment_summary_by_booking already
        reads a booking's money (sum of all rows = total, sum of the
        is_outstanding rows = owed), so a reservation entered here shows up
        correctly on the calendar's "payment incomplete" status and the daily
        staff view without any special-casing.
        """
        if not self.membership.can_see_money:
            return
        total = data.get("total_amount")
        paid = data.get("amount_paid") or 0
        if total:
            paid = min(paid, total)
            if paid > 0:
                BookingPayment.objects.create(
                    organization=org, booking=booking, kind=BookingPayment.Kind.DIRECT,
                    amount=paid, is_outstanding=False, received_on=timezone.localdate(),
                )
            owed = total - paid
            if owed > 0:
                BookingPayment.objects.create(
                    organization=org, booking=booking, kind=BookingPayment.Kind.DIRECT,
                    amount=owed, is_outstanding=True,
                )
        elif paid:
            BookingPayment.objects.create(
                organization=org, booking=booking, kind=BookingPayment.Kind.DIRECT,
                amount=paid, is_outstanding=False, received_on=timezone.localdate(),
            )

    def _render(self, form):
        room_types_by_villa: dict = {}
        for room_type in form.fields["room_type"].queryset:
            room_types_by_villa.setdefault(room_type.villa_id, []).append(
                {"id": room_type.id, "name": room_type.name}
            )
        villas_json = [
            {"id": v.id, "name": v.name, "room_types": room_types_by_villa.get(v.id, [])}
            for v in self.villas
        ]
        post = self.request.POST
        # Passed to reservation_form.js's Alpine component through json_script
        # (see add.html) rather than interpolated straight into the x-data
        # attribute string, so a value a person typed can never break out of
        # the JS it's embedded in.
        reservation_config = {
            "villaId": form["villa"].value() or "",
            "roomTypeId": form["room_type"].value() or "",
            "nationality": form["nationality"].value() or "",
            "totalRaw": form["total_amount"].value() or "" if "total_amount" in form.fields else "",
            "paidRaw": form["amount_paid"].value() or "" if "amount_paid" in form.fields else "",
            "roomTypeNoVillaLabel": str(_("Choose a villa first")),
            "roomTypeReadyLabel": str(_("Choose a room type")),
        }
        context = {
            "form": form,
            "villas_json": villas_json,
            "reservation_config": reservation_config,
            "can_see_money": self.membership.can_see_money,
            "nationality_pending": self.request.GET.get("nationality_pending") == "1",
        }
        # Re-shows the nights/availability preview after a rejected submit
        # (e.g. a missing full name) so the dates the guest checked don't
        # silently reset to blank along with everything else on the page.
        context.update(_reservation_preview(
            self.villas, post.get("room_type"),
            _parse_date(post.get("check_in")), _parse_date(post.get("check_out")),
        ))
        return render(self.request, self.template_name, context)


def _reservation_preview(villas, room_type_id, check_in, check_out):
    """Nights + room-availability, shared by the Add Reservation page's own
    render (a freshly loaded form, or one bounced back with other errors) and
    ReservationAvailabilityView's live HTMX version of the same preview.
    """
    room_type = RoomCategory.objects.filter(
        villa_id__in=[v.id for v in villas], pk=room_type_id or None,
    ).first()
    valid_range = bool(check_in and check_out and check_out > check_in)

    context = {"nights": (check_out - check_in).days if valid_range else None, "availability": None}
    if room_type and valid_range:
        room, conflict = find_available_room(room_type, check_in, check_out)
        if room is not None:
            context["availability"] = {"free": True}
        else:
            context["availability"] = {
                "free": False,
                "guest": conflict.guest.full_name if conflict.guest else _("a guest"),
                "check_in": conflict.check_in,
                "check_out": conflict.check_out,
            }
    return context


class ReservationAvailabilityView(LoginRequiredMixin, View):
    """Live nights + room-availability preview for the Add Reservation form,
    called by HTMX every time the villa, room type, or either date changes.
    Purely a preview - ReservationForm.clean() re-runs the same check at
    submit time and is the only place that's actually trusted.
    """

    def get(self, request):
        if request.organization is None:
            return HttpResponse("")
        villas, _membership = scoped_villas(request)
        context = _reservation_preview(
            villas, request.GET.get("room_type"),
            _parse_date(request.GET.get("check_in")), _parse_date(request.GET.get("check_out")),
        )
        return render(request, "bookings/_reservation_availability.html", context)


def _scoped_booking(request, pk):
    """The one booking behind `pk`, if the current user is allowed to see it -
    same villa-scoping the calendar's own read path uses (scoped_villas), so
    a staff member restricted to certain villas can't remove or reschedule a
    booking on one they can't otherwise see.
    """
    villas, _membership = scoped_villas(request)
    return get_object_or_404(
        Booking.objects.filter(organization=request.organization, villa_id__in=[v.id for v in villas]),
        pk=pk,
    )


class BookingRemoveView(LoginRequiredMixin, View):
    """Cancels a booking - never deletes the row. BookingPayment.booking is
    CASCADE, so a hard delete would take any payment/financial history down
    with it; CANCELLED is already excluded everywhere the calendar queries
    Booking (see _calendar_query in services.py), so a cancelled booking just
    stops appearing, with no other change needed anywhere.
    """

    def post(self, request, pk):
        booking = _scoped_booking(request, pk)
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status", "updated_at"])
        logger.info("Booking %s cancelled by user %s", booking.pk, request.user.pk)
        messages.success(request, _("Booking removed."))
        return redirect(safe_next(request, reverse("bookings:calendar")))


class BookingRescheduleView(LoginRequiredMixin, View):
    """Drag-move / drag-resize on the calendar. The client only ever proposes
    new dates/room for the confirm dialog's preview text - nothing here
    trusts that math. Re-validates through Booking.full_clean() (covers the
    check_out > check_in constraint and Booking.clean()'s room/villa match)
    plus an explicit same-room overlap check, since nothing in Booking.Meta
    otherwise stops two live bookings overlapping in one room.
    """

    def post(self, request, pk):
        booking = _scoped_booking(request, pk)

        check_in = _parse_date(request.POST.get("check_in"))
        check_out = _parse_date(request.POST.get("check_out"))
        if not check_in or not check_out:
            return JsonResponse({"ok": False, "error": _("Invalid dates.")}, status=400)

        room = booking.room
        room_id = request.POST.get("room_id")
        if room_id and str(room_id) != str(booking.room_id):
            room = get_object_or_404(Room.objects.filter(villa=booking.villa, is_active=True), pk=room_id)

        overlap = (
            Booking.objects.filter(
                organization=request.organization, room=room,
                check_in__lt=check_out, check_out__gt=check_in,
            )
            .exclude(pk=booking.pk)
            .exclude(status=Booking.Status.CANCELLED)
            .exists()
        )
        if overlap:
            return JsonResponse(
                {"ok": False, "error": _("That room is already booked for part of those dates.")},
                status=409,
            )

        booking.check_in, booking.check_out, booking.room = check_in, check_out, room
        try:
            booking.full_clean()
        except ValidationError as exc:
            errors = sum((list(v) for v in exc.message_dict.values()), [])
            return JsonResponse({"ok": False, "error": " ".join(str(e) for e in errors)}, status=400)

        booking.save(update_fields=["check_in", "check_out", "room", "updated_at"])
        logger.info(
            "Booking %s rescheduled to %s–%s (room %s) by user %s",
            booking.pk, check_in, check_out, room.pk if room else None, request.user.pk,
        )
        return JsonResponse({"ok": True})


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
    today = timezone.localdate()
    return {
        # Centers today in the visible range (e.g. 7-day view: 3 days back, 3
        # forward) rather than pinning it as the first column, so jumping back
        # from a future month lands the way the button is drawn - today in
        # the middle, not at the left edge.
        "today": _tab_href(request, start=(today - timedelta(days=days // 2)).isoformat()),
        "day_back": _tab_href(request, start=(start - timedelta(days=1)).isoformat()),
        "day_forward": _tab_href(request, start=(start + timedelta(days=1)).isoformat()),
        "range_back": _tab_href(request, start=(start - timedelta(days=days)).isoformat()),
        "range_forward": _tab_href(request, start=(start + timedelta(days=days)).isoformat()),
    }

"""Owner reporting dashboard (feature #5).

One screen: today's occupancy, this month's revenue, and who's arriving,
leaving, and still owes money - the last three now laid out to match the
design handoff's "Today" screen (New UI mockups/design_handoff_villa_
dashboard/README.md). Reporting has no booking logic of its own, only the
aggregation and the currency conversion for display.
"""

import logging
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from apps.bookings.models import Booking, BookingPayment
from apps.compliance.views import _documents_needing_attention, _upcoming_police_reports
from apps.organizations.mixins import ManagerRequiredMixin
from apps.reporting import reports
from apps.reporting.fx import convert
from apps.sync.models import SyncAccount
from apps.villas.models import Villa

logger = logging.getLogger(__name__)

OCCUPYING_STATUSES = [Booking.Status.CONFIRMED, Booking.Status.BLOCKED]


class DashboardView(ManagerRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization

        if org is None:
            # A logged-in account with no operator membership - the superuser
            # created for admin access is like this by design. Nothing below
            # is tenant-scoped, so stop rather than guess whose data to show.
            context["no_organization"] = True
            return context

        today = timezone.localdate()
        month_start = today.replace(day=1)

        bookings_today = Booking.objects.filter(
            organization=org, check_in__lte=today, check_out__gt=today,
            status__in=OCCUPYING_STATUSES,
        ).select_related("villa", "room", "guest").order_by("villa__name")

        arriving_today = (
            Booking.objects.filter(organization=org, check_in=today, status=Booking.Status.CONFIRMED)
            .select_related("villa", "guest").order_by("villa__name")
        )
        departing_today = (
            Booking.objects.filter(organization=org, check_out=today, status=Booking.Status.CONFIRMED)
            .select_related("villa", "guest").order_by("villa__name")
        )
        outstanding_payments = (
            BookingPayment.objects.filter(organization=org, is_outstanding=True)
            .select_related("booking", "booking__villa", "booking__guest").order_by("booking__check_in")
        )

        villas = Villa.objects.filter(organization=org).live().order_by("name")
        total_villas = villas.count()
        live_villa_ids = {villa.id for villa in villas}
        # A booking can still point at a villa that has since been archived, so
        # only count the ones we are actually showing on this page.
        occupied_villa_ids = set(bookings_today.values_list("villa_id", flat=True)) & live_villa_ids
        occupied_villas = len(occupied_villa_ids)
        occupancy_percent = round(occupied_villas / total_villas * 100) if total_villas else 0

        # Room-level split per villa - a villa with 10 rooms and 6 booked
        # today shows "60% - 6/10", not just an occupied/vacant flag.
        room_counts = {villa.id: villa.rooms.count() for villa in villas}
        occupied_room_counts = {villa.id: 0 for villa in villas}
        for booking in bookings_today:
            # "Night 1 of 3" etc. - the Occupied-today card's per-row meta.
            booking.night_of_stay = (today - booking.check_in).days + 1
            booking.room_label = (
                f"{booking.villa.name} · {booking.room.name}" if booking.room_id else booking.villa.name
            )
            if booking.room_id and booking.villa_id in occupied_room_counts:
                occupied_room_counts[booking.villa_id] += 1

        villa_occupancy = []
        for villa in villas:
            total_rooms = room_counts[villa.id]
            occupied_rooms = min(occupied_room_counts[villa.id], total_rooms) if total_rooms else 0
            villa_percent = round(occupied_rooms / total_rooms * 100) if total_rooms else 0
            villa_occupancy.append({
                "villa": villa,
                "occupied": villa.id in occupied_villa_ids,
                "occupied_rooms": occupied_rooms,
                "total_rooms": total_rooms,
                "occupancy_percent": villa_percent,
            })

        revenue_this_month, unconverted_count = self._revenue_this_month(org, month_start, today)

        # Same helpers the compliance action-needed page uses, so this card's
        # count always matches what "Needs doing" actually links to.
        needs_doing = len(_documents_needing_attention(self.request))
        overdue_reports = _upcoming_police_reports(self.request).count()

        context.update(
            today=today,
            occupancy_percent=occupancy_percent,
            occupied_villas=occupied_villas,
            total_villas=total_villas,
            villa_occupancy=villa_occupancy,
            revenue_this_month=revenue_this_month,
            revenue_unconverted_count=unconverted_count,
            bookings_today=bookings_today,
            arriving_today=arriving_today,
            departing_today=departing_today,
            outstanding_payments=outstanding_payments,
            needs_doing_count=needs_doing + overdue_reports,
        )
        return context

    def _revenue_this_month(self, org, month_start, today):
        """Sum received payments this month, converted to the org's own
        reporting currency. A payment with no exchange rate on file is left
        out of the total rather than guessed at - see apps/reporting/fx.py -
        and counted separately so the number is never silently short.
        """
        payments = BookingPayment.objects.filter(
            organization=org, is_outstanding=False,
            received_on__gte=month_start, received_on__lte=today,
        )
        total = 0
        unconverted = 0
        for payment in payments:
            converted = convert(payment.amount, payment.currency, org.default_currency, payment.received_on)
            if converted is None:
                unconverted += 1
            else:
                total += converted
        return total, unconverted


class ReportsView(ManagerRequiredMixin, TemplateView):
    """The /reporting screen. Everything on it comes from the database - see
    apps/reporting/reports.py for how each number is worked out."""

    template_name = "reporting/reports.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        if org is None:
            context["no_organization"] = True
            return context

        today = timezone.localdate()
        range_key = self.request.GET.get("range", reports.DEFAULT_RANGE)
        if range_key not in dict(reports.RANGE_CHOICES):
            range_key = reports.DEFAULT_RANGE
        period = reports.resolve_period(range_key, today)
        previous = period.previous()

        all_villas = list(Villa.objects.filter(organization=org).live().order_by("name"))
        villa_filter = self.request.GET.get("villa", "all")
        chosen = [v for v in all_villas if str(v.id) == villa_filter]
        villas = chosen or all_villas
        if not chosen:
            villa_filter = "all"

        logger.info(
            "reports: org=%s range=%s (%s..%s) villa=%s villas=%d",
            org.id, range_key, period.start, period.end, villa_filter, len(villas),
        )

        data = reports.ReportData(org, villas, period)
        prior = reports.ReportData(org, villas, previous)

        received, received_by_villa = data.received(period.start, period.end)
        value, value_by_villa = data.booking_value(period.start, period.end)
        occupancy, booked_nights, available_nights, occ_by_villa = data.occupancy(
            period.start, period.end
        )
        avg_nightly, avg_by_villa = data.avg_nightly(period.start, period.end)

        prev_received, _ = prior.received(previous.start, previous.end, count_gaps=False)
        prev_value, _ = prior.booking_value(previous.start, previous.end, count_gaps=False)
        prev_occupancy, _, prev_available, _ = prior.occupancy(previous.start, previous.end)
        prev_avg, _ = prior.avg_nightly(previous.start, previous.end)

        per_night = received / available_nights if available_nights else None
        prev_per_night = prev_received / prev_available if prev_available else None

        context.update(
            range_key=range_key,
            range_options=[
                {"key": key, "label": label, "active": key == range_key}
                for key, label in reports.RANGE_CHOICES
            ],
            villa_options=all_villas,
            villa_filter=villa_filter,
            period=period,
            currency=org.default_currency,
            has_any_data=bool(
                received or value or booked_nights or data.unconverted_payments
            ),
            metrics=self._metrics(
                org, received, prev_received, value, prev_value, occupancy,
                prev_occupancy, avg_nightly, prev_avg, per_night, prev_per_night,
            ),
            unconverted_payments=data.unconverted_payments,
            bookings_without_price=data.bookings_without_price,
            earnings_bars=self._earnings_bars(org, villas, period),
            occupancy_trend=self._occupancy_trend(org, villas, period),
            source_shares=self._source_shares(org, villas, period),
            nationalities=self._nationalities(org, villas, period),
            villa_rows=self._villa_rows(
                villas, received_by_villa, value_by_villa, occ_by_villa, avg_by_villa
            ),
            owed_groups=self._owed_groups(org, villas, today),
            freshness=self._freshness(org, villas),
        )
        return context

    # -- pieces ------------------------------------------------------------

    def _metrics(self, org, received, prev_received, value, prev_value, occupancy,
                 prev_occupancy, avg_nightly, prev_avg, per_night, prev_per_night):
        return [
            {
                "label": _("Money received"),
                "value": received,
                "is_money": True,
                "change": reports.change(received, prev_received),
            },
            {
                "label": _("Value of bookings made"),
                "value": value,
                "is_money": True,
                "change": reports.change(value, prev_value),
                "note": _("Includes stays not paid for yet."),
            },
            {
                "label": _("How full the villas were"),
                "value": occupancy,
                "is_percent": True,
                "change": reports.change(occupancy, prev_occupancy),
            },
            {
                "label": _("Average price per night"),
                "value": avg_nightly,
                "is_money": True,
                "change": reports.change(avg_nightly, prev_avg),
            },
            {
                "label": _("Money received per night, including empty ones"),
                "value": per_night,
                "is_money": True,
                "change": reports.change(per_night, prev_per_night),
            },
        ]

    def _trend_months(self, period):
        """The last TREND_MONTHS months ending with the period's own last month."""
        last = reports.month_start(period.end)
        months = []
        for offset in range(reports.TREND_MONTHS - 1, -1, -1):
            start = reports.add_months(last, -offset)
            months.append((start, reports.add_months(start, 1) - timedelta(days=1)))
        return months

    def _earnings_bars(self, org, villas, period):
        months = self._trend_months(period)
        data = reports.ReportData(org, villas, period)
        totals = [data.received(start, end, count_gaps=False)[0] for start, end in months]
        top = max(totals) if totals else 0
        bar_w = (
            reports.CHART_W - reports.CHART_PAD * 2 - reports.BAR_GAP * (len(months) - 1)
        ) / len(months)
        bars = []
        for index, ((start, _end), total) in enumerate(zip(months, totals, strict=False)):
            height = float(total) / float(top) * (reports.CHART_H - 40) if top else 0
            x = reports.CHART_PAD + index * (bar_w + reports.BAR_GAP)
            bars.append({
                "x": round(x, 1), "y": round(reports.CHART_H - 30 - height, 1),
                "w": round(bar_w, 1), "h": round(height, 1),
                "label_x": round(x + bar_w / 2, 1),
                "month": start.strftime("%b"), "total": total,
            })
        return {"bars": bars, "empty": not top, "color": reports.BAR_COLOR}

    def _occupancy_trend(self, org, villas, period):
        months = self._trend_months(period)
        data = reports.ReportData(org, villas, period)
        bar_w = (
            reports.CHART_W - reports.CHART_PAD * 2 - reports.BAR_GAP * (len(months) - 1)
        ) / len(months)
        dots = []
        for index, (start, end) in enumerate(months):
            pct = data.occupancy(start, end)[0]
            x = reports.CHART_PAD + index * (bar_w + reports.BAR_GAP) + bar_w / 2
            y = reports.CHART_H - 30 - (pct / 100) * (reports.CHART_H - 70)
            dots.append({
                "x": round(x, 1), "y": round(y, 1),
                "month": start.strftime("%b"), "pct": pct,
            })
        return {
            "dots": dots,
            "points": " ".join(f"{d['x']},{d['y']}" for d in dots),
            "empty": not any(d["pct"] for d in dots),
            "color": reports.LINE_COLOR,
        }

    def _source_shares(self, org, villas, period):
        rows = (
            Booking.objects.filter(
                organization=org, villa__in=villas, status=Booking.Status.CONFIRMED,
                check_in__lte=period.end, check_out__gt=period.start,
            )
            .values("channel").annotate(n=Count("id")).order_by("-n")
        )
        total = sum(row["n"] for row in rows)
        shares = []
        for row in rows:
            channel = row["channel"]
            shares.append({
                "name": dict(Booking.Channel.choices).get(channel, channel),
                "pct": reports.percent(row["n"], total),
                "count": row["n"],
                "color": reports.CHANNEL_COLORS.get(channel, reports.OTHER_COLOR),
            })
        return {"shares": shares, "total": total}

    def _nationalities(self, org, villas, period):
        rows = (
            Booking.objects.filter(
                organization=org, villa__in=villas, status=Booking.Status.CONFIRMED,
                check_in__lte=period.end, check_out__gt=period.start,
                guest__isnull=False,
            )
            .exclude(guest__nationality="")
            .values("guest__nationality").annotate(n=Count("id")).order_by("-n")
        )
        total = sum(row["n"] for row in rows)
        listed = []
        for row in rows[:9]:
            code = row["guest__nationality"]
            listed.append({
                "country": reports.NATIONALITY_LABELS.get(code, code),
                "pct": reports.percent(row["n"], total),
                "color": reports.NATIONALITY_COLOR,
            })
        rest = sum(row["n"] for row in rows[9:])
        if rest:
            listed.append({
                "country": _("Everyone else"),
                "pct": reports.percent(rest, total),
                "color": reports.OTHER_COLOR,
            })
        domestic = next((row["n"] for row in rows if row["guest__nationality"] == "ID"), 0)
        # Stays with no nationality on file are not guessed at - they are
        # counted here so the page can say how much it doesn't know.
        unknown = Booking.objects.filter(
            organization=org, villa__in=villas, status=Booking.Status.CONFIRMED,
            check_in__lte=period.end, check_out__gt=period.start,
        ).filter(Q(guest__isnull=True) | Q(guest__nationality="")).count()
        return {
            "rows": listed,
            "total": total,
            "domestic_pct": reports.percent(domestic, total),
            "unknown": unknown,
        }

    def _villa_rows(self, villas, received_by_villa, value_by_villa, occ_by_villa,
                    avg_by_villa):
        rows = []
        for villa in villas:
            received = received_by_villa.get(villa.id)
            value = value_by_villa.get(villa.id)
            occupancy = occ_by_villa.get(villa.id, 0)
            rows.append({
                "villa": villa,
                "received": received,
                "value": value,
                "occupancy": occupancy,
                "avg_nightly": avg_by_villa.get(villa.id),
                "has_data": bool(received or value or occupancy),
            })
        rows.sort(key=lambda r: (r["received"] or 0, r["value"] or 0), reverse=True)
        return rows

    def _owed_groups(self, org, villas, today):
        """Outstanding money, grouped by when the stay starts.

        BookingPayment has no due date of its own, so check-in stands in for
        one: a stay that has already begun and still owes money is overdue.
        """
        payments = list(
            BookingPayment.objects.filter(
                organization=org, is_outstanding=True, booking__villa__in=villas,
            )
            .select_related("booking", "booking__villa", "booking__guest")
            .order_by("booking__check_in")
        )
        buckets = {"overdue": [], "now": [], "week": [], "later": []}
        for payment in payments:
            check_in = payment.booking.check_in
            if check_in < today:
                buckets["overdue"].append(payment)
            elif check_in == today:
                buckets["now"].append(payment)
            elif check_in <= today + timedelta(days=7):
                buckets["week"].append(payment)
            else:
                buckets["later"].append(payment)
        labels = [
            ("overdue", _("Overdue"), True),
            ("now", _("Due today"), True),
            ("week", _("Due this week"), False),
            ("later", _("Later"), False),
        ]
        return [
            {"key": key, "label": label, "urgent": urgent, "items": buckets[key]}
            for key, label, urgent in labels
        ]

    def _freshness(self, org, villas):
        accounts = (
            SyncAccount.objects.filter(organization=org, is_active=True)
            .select_related("villa").order_by("provider", "label")
        )
        villa_ids = {v.id for v in villas}
        rows = []
        for account in accounts:
            if account.villa_id and account.villa_id not in villa_ids:
                continue
            live = account.provider == SyncAccount.Provider.BEDS24
            rows.append({
                "name": account.label or account.get_provider_display(),
                "villa": account.villa,
                "live": live,
                "last_success_at": account.last_success_at,
                "has_error": bool(account.last_error),
            })
        return rows

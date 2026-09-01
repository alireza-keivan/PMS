"""Owner reporting dashboard (feature #5).

One screen: today's occupancy, this month's revenue, and who's arriving,
leaving, and still owes money - the last three now laid out to match the
design handoff's "Today" screen (New UI mockups/design_handoff_villa_
dashboard/README.md). Reporting has no booking logic of its own, only the
aggregation and the currency conversion for display.
"""

from django.utils import timezone
from django.views.generic import TemplateView

from apps.bookings.models import Booking, BookingPayment
from apps.compliance.models import ComplianceDocument, PoliceReport
from apps.organizations.mixins import ManagerRequiredMixin
from apps.reporting.fx import convert
from apps.villas.models import Villa

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

        needs_doing = sum(
            1 for d in ComplianceDocument.objects.filter(organization=org) if d.needs_attention
        )
        overdue_reports = sum(
            1 for p in PoliceReport.objects.filter(organization=org, status=PoliceReport.Status.NEEDED)
            if p.is_overdue
        )

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

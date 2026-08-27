"""Owner reporting dashboard (feature #5).

One screen: today's occupancy, this month's revenue, who's arriving, who's
leaving, and who still owes money. Everything here is a read of data other
apps already own - reporting has no booking logic of its own, only the
aggregation and the currency conversion for display.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from apps.bookings.models import Booking, BookingPayment
from apps.compliance.models import ComplianceDocument, PoliceReport
from apps.reporting.fx import convert
from apps.villas.models import Villa

OCCUPYING_STATUSES = [Booking.Status.CONFIRMED, Booking.Status.BLOCKED]


class DashboardView(LoginRequiredMixin, TemplateView):
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
        ).select_related("villa", "guest")

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

        total_villas = Villa.objects.filter(organization=org, is_active=True).count()
        occupied_villas = bookings_today.values("villa_id").distinct().count()
        occupancy_percent = round(occupied_villas / total_villas * 100) if total_villas else 0

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

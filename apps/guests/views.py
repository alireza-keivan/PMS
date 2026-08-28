"""Staff-facing reservation search - one row per booking, grouped by date.

Guest *profile* lookup (one row per person, their whole history) still lives
in GuestDetailView below. ReservationListView is the operator's day-to-day
"find a booking" screen - modelled on the Beds24-style reservations search
staff already know, so it filters and groups by stay dates rather than by
guest.
"""

from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import DetailView, TemplateView

from apps.bookings.models import Booking
from apps.bookings.services import payment_summary_by_booking, scoped_villas
from apps.guests.models import Guest

DATE_TYPE_CHOICES = ("check_in", "check_out")
DEFAULT_DATE_TYPE = "check_in"
DEFAULT_RANGE_DAYS = 30


class ReservationListView(LoginRequiredMixin, TemplateView):
    template_name = "guests/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        if org is None:
            context["no_organization"] = True
            return context

        today = timezone.localdate()
        date_type = self.request.GET.get("date_type", DEFAULT_DATE_TYPE)
        if date_type not in DATE_TYPE_CHOICES:
            date_type = DEFAULT_DATE_TYPE
        date_from = _parse_date(self.request.GET.get("date_from")) or today
        date_to = _parse_date(self.request.GET.get("date_to")) or (today + timedelta(days=DEFAULT_RANGE_DAYS))
        status = self.request.GET.get("status", "")
        source = self.request.GET.get("source", "")
        guest_name = self.request.GET.get("guest_name", "").strip()
        villa_id = self.request.GET.get("villa", "")

        villas, _membership = scoped_villas(self.request)
        villa_ids = [v.id for v in villas]
        if villa_id:
            try:
                villa_id = int(villa_id)
            except ValueError:
                villa_id = ""
            else:
                villa_ids = [v for v in villa_ids if v == villa_id]

        bookings = Booking.objects.filter(
            organization=org, villa_id__in=villa_ids,
            **{f"{date_type}__gte": date_from, f"{date_type}__lte": date_to},
        ).select_related("villa", "guest")
        if status:
            bookings = bookings.filter(status=status)
        if source:
            bookings = bookings.filter(channel=source)
        if guest_name:
            bookings = bookings.filter(guest__full_name__icontains=guest_name)
        bookings = list(bookings.order_by(date_type))

        payments = payment_summary_by_booking(org, [b.id for b in bookings])

        context.update(
            no_organization=False,
            groups=_group_by_date(bookings, payments, date_type),
            total_count=len(bookings),
            date_type=date_type,
            date_from=date_from,
            date_to=date_to,
            status=status,
            source=source,
            guest_name=guest_name,
            villa_id=villa_id,
            villas=villas,
            status_choices=Booking.Status.choices,
            channel_choices=Booking.Channel.choices,
        )
        return context


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _group_by_date(bookings, payments, date_type):
    """Bookings are already ordered by date_type, so same-date rows are
    always consecutive - no need to build and sort a dict of buckets.
    """
    groups = []
    current_date = None
    current_rows = None
    for booking in bookings:
        booking_date = getattr(booking, date_type)
        if booking_date != current_date:
            current_date = booking_date
            current_rows = []
            groups.append({"date": current_date, "rows": current_rows})
        payment = payments.get(booking.id, {})
        current_rows.append({
            "booking": booking,
            "total_amount": payment.get("total_amount"),
            "amount_owed": payment.get("amount_owed"),
            "currency": payment.get("currency"),
        })
    return groups


class GuestDetailView(LoginRequiredMixin, DetailView):
    template_name = "guests/detail.html"
    context_object_name = "guest"

    def get_queryset(self):
        org = self.request.organization
        return Guest.objects.filter(organization=org) if org else Guest.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        guest = self.object
        context["bookings"] = guest.bookings.select_related("villa").order_by("-check_in")
        context["requests"] = guest.requests.select_related("booking").order_by("-created_at")
        context["feedback_entries"] = guest.feedback.order_by("-created_at")
        context["police_reports"] = guest.police_reports.select_related("booking").order_by("-deadline")
        context["recent_activity"] = guest.activity.order_by("-occurred_at")[:20]
        return context

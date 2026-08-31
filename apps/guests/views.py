"""Guest *profile* lookup (one row per person, their whole history) - see
GuestDetailView below.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import formats
from django.views.generic import DetailView

from apps.guests.models import Guest
from apps.guests.services import guest_spend_summary


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

        membership = self.request.user.memberships.get(organization=guest.organization)
        if membership.can_see_money:
            summary = guest_spend_summary(guest)
            context["total_expenditure"] = _format_money(summary.get("total_amount"), summary.get("currency"))
            context["amount_due"] = _format_money(summary.get("amount_owed"), summary.get("currency"))
        else:
            context["total_expenditure"] = None
            context["amount_due"] = None
        context["can_see_money"] = membership.can_see_money
        return context


def _format_money(amount, currency):
    """"Rp 1,500,000" (or the source currency's own code) - never a bare
    number, since an unlabelled figure invites misreading it in the wrong
    currency (see apps.bookings.services._money for the same grouping rule).
    """
    if not amount:
        return None
    formatted = formats.number_format(amount, decimal_pos=0, force_grouping=True)
    prefix = "Rp" if not currency or currency == "IDR" else currency
    return f"{prefix} {formatted}"

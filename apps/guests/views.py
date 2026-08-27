"""Staff-facing guest directory - one record per person, not per booking.

Read-only. Guest rows are created by the sync pipeline and the guest portal
(see apps/guests/services.py); nothing here writes to a guest record, it just
brings together what is already on file for staff to look someone up.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import DetailView, ListView

from apps.guests.models import Guest


class GuestListView(LoginRequiredMixin, ListView):
    template_name = "guests/list.html"
    context_object_name = "guests"
    paginate_by = 25

    def get_queryset(self):
        org = self.request.organization
        if org is None:
            return Guest.objects.none()

        queryset = Guest.objects.filter(organization=org)
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(full_name__icontains=query)
                | Q(email__icontains=query)
                | Q(phone__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["no_organization"] = self.request.organization is None
        context["query"] = self.request.GET.get("q", "")
        return context


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

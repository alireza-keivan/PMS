"""Staff-facing guest screens.

Two of them: one guest's whole history (GuestDetailView), and the queue of what
guests have asked for across every villa this user can see
(GuestRequestListView).

The guest's own side of this lives in apps/guests/portal_views.py and shares
nothing with these - different door, different scoping rules.
"""

import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import formats, timezone
from django.views.generic import DetailView, ListView, View

from apps.guests.models import Guest, GuestRequest
from apps.guests.services import guest_spend_summary
from apps.guests.tokens import portal_url, portal_window
from apps.organizations.permissions import can_see_money as _can_see_money
from apps.organizations.scoping import scoped_villas

logger = logging.getLogger(__name__)

OPEN_STATUSES = (GuestRequest.Status.NEW, GuestRequest.Status.SEEN)


class GuestDetailView(LoginRequiredMixin, DetailView):
    template_name = "guests/detail.html"
    context_object_name = "guest"

    def get_queryset(self):
        org = self.request.organization
        if org is None:
            return Guest.objects.none()
        villas, _membership = scoped_villas(self.request)
        return Guest.objects.filter(
            organization=org, bookings__villa_id__in=[v.id for v in villas]
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        guest = self.object
        context["bookings"] = guest.bookings.select_related("villa").order_by("-check_in")
        context["requests"] = guest.requests.select_related("booking").order_by("-created_at")
        context["feedback_entries"] = guest.feedback.order_by("-created_at")
        context["police_reports"] = guest.police_reports.select_related("booking").order_by("-deadline")
        context["recent_activity"] = guest.activity.order_by("-occurred_at")[:20]

        can_see_money = _can_see_money(self.request.user)
        if can_see_money:
            summary = guest_spend_summary(guest)
            context["total_expenditure"] = _format_money(summary.get("total_amount"), summary.get("currency"))
            context["amount_due"] = _format_money(summary.get("amount_owed"), summary.get("currency"))
        else:
            context["total_expenditure"] = None
            context["amount_due"] = None
        context["can_see_money"] = can_see_money
        context["portal_link"] = _sendable_portal_link(self.request, guest)
        return context


class GuestRequestListView(LoginRequiredMixin, ListView):
    """Everything guests have asked for, newest first.

    This list *is* how staff find out about a request today. The WhatsApp
    nudge that should also fire is build order step 3 and isn't built, so
    nothing here may suggest a staff member was messaged - a request with
    notified_at still null was seen because somebody opened this page.
    """

    template_name = "guests/requests.html"
    context_object_name = "requests"

    def get_queryset(self):
        queryset = _scoped_requests(self.request)
        if self.show_done():
            return queryset
        return queryset.filter(status__in=OPEN_STATUSES)

    def show_done(self) -> bool:
        return self.request.GET.get("show") == "all"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["no_organization"] = self.request.organization is None
        context["show_done"] = self.show_done()
        context["open_count"] = (
            0 if context["no_organization"]
            else _scoped_requests(self.request).filter(status__in=OPEN_STATUSES).count()
        )
        return context

    def get_template_names(self):
        # Same URL serves the whole page and, to HTMX, just the list - so the
        # filter can swap in place while the address stays shareable. Same
        # shape as apps/messaging/views.py.
        if self.request.htmx:
            return ["guests/_request_rows.html"]
        return [self.template_name]


class GuestRequestStatusView(LoginRequiredMixin, View):
    """Staff moves a request along: seen, done, or back to open.

    Not booking or availability data, so CLAUDE.md rule 5's confirm-before-
    writing requirement doesn't apply - this is the same kind of write as
    marking a police report done in apps/compliance/views.py.
    """

    ALLOWED = {
        GuestRequest.Status.NEW,
        GuestRequest.Status.SEEN,
        GuestRequest.Status.DONE,
        GuestRequest.Status.CANCELLED,
    }

    def post(self, request, pk):
        status = request.POST.get("status")
        if status not in self.ALLOWED:
            logger.warning(
                "Refused an unknown status %r for guest request %s from user %s",
                status, pk, request.user.pk,
            )
            # Empty body on purpose: HTMX leaves the row alone on a 4xx, so
            # there is nothing to swap in and nothing on screen changes.
            return HttpResponseBadRequest()

        guest_request = get_object_or_404(_scoped_requests(request), pk=pk)
        guest_request.status = status
        guest_request.save(update_fields=["status", "updated_at"])

        logger.info(
            "Guest request %s moved to %s by user %s", guest_request.pk, status, request.user.pk
        )
        return render(
            request, "guests/_request_row.html",
            {"r": guest_request, "now": timezone.now()},
        )


def _sendable_portal_link(request, guest) -> str:
    """The guest's page link, if there is one worth sending right now.

    Only for a stay whose link actually opens today. A link for a booking three
    weeks out would show the guest the "this link doesn't work" page, so
    handing it to staff to paste into WhatsApp would be a trap - better to show
    nothing and let them come back nearer the date.
    """
    from apps.bookings.models import Booking

    today = timezone.localdate()
    bookings = guest.bookings.select_related("villa").filter(status=Booking.Status.CONFIRMED)
    for booking in bookings.order_by("check_in"):
        opens_on, closes_on = portal_window(booking)
        if opens_on <= today <= closes_on:
            return request.build_absolute_uri(portal_url(booking))
    return ""


def _scoped_requests(request):
    """Requests on villas this user is allowed to see, and no others.

    One place rather than repeated in each view, so a future screen can't
    quietly forget the villa filter and leak another operator's guests.
    """
    org = request.organization
    if org is None:
        return GuestRequest.objects.none()
    villas, _membership = scoped_villas(request)
    return GuestRequest.objects.filter(
        organization=org, booking__villa_id__in=[v.id for v in villas]
    ).select_related("guest", "booking", "booking__villa")


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

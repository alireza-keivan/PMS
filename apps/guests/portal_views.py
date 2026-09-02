"""The guest's own page, at /stay/<token>/.

Kept in its own module so that "is this view guest-facing?" is answered by the
filename. Three rules hold for everything in here, without exception:

  1. No LoginRequiredMixin, no request.user, no request.organization. The
     visitor has no account and the organization middleware leaves them None.
  2. Never call apps.organizations.scoping.scoped_villas - it reads
     request.user.memberships and there is no user. Everything on the page
     comes off the booking the token resolved to, and nothing else.
  3. Never show anything the guest didn't tell us. No money, no Guest.notes,
     no other bookings, no other guests. The signed link proves which booking
     someone holds - it is not a login, and it grants nothing wider.
"""

import logging

from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, View

from apps.guests.forms import GuestRequestForm
from apps.guests.models import GuestActivity, GuestRequest
from apps.guests.services import log_activity
from apps.guests.tokens import resolve_booking

logger = logging.getLogger(__name__)

# How many things a guest can have outstanding before the form stops taking
# more. Not a rate limiter - just a floor under the obvious failure, which is
# a bored guest tapping "cleaning" thirty times and burying the staff list.
MAX_OPEN_REQUESTS = 10

OPEN_STATUSES = (GuestRequest.Status.NEW, GuestRequest.Status.SEEN)


class PortalAccessMixin:
    """Turns the token in the URL into a booking, or closes the door.

    Sets self.booking, self.guest and self.villa for the view. Anything the
    token doesn't open renders the same friendly page - see resolve_booking for
    why every rejection has to look identical from outside.
    """

    def dispatch(self, request, *args, **kwargs):
        self.booking = resolve_booking(kwargs.get("token", ""))
        if self.booking is None:
            return self.link_closed(request)
        self.guest = self.booking.guest
        self.villa = self.booking.villa
        return super().dispatch(request, *args, **kwargs)

    def link_closed(self, request):
        # 404 rather than 403: from the visitor's side there is no such page,
        # and there is nothing they could do differently to get in.
        return render(request, "portal/link_closed.html", status=404)

    def open_requests(self):
        return self.booking.requests.filter(status__in=OPEN_STATUSES)

    def portal_context(self, **extra):
        context = {
            "booking": self.booking,
            "guest": self.guest,
            "villa": self.villa,
            "requests": self.booking.requests.order_by("-created_at"),
            "token": self.kwargs["token"],
        }
        context.update(extra)
        return context


class PortalHomeView(PortalAccessMixin, TemplateView):
    """The whole portal, on one screen: your stay, and what you can ask for."""

    template_name = "portal/home.html"

    def get(self, request, *args, **kwargs):
        log_activity(self.guest, GuestActivity.Kind.PORTAL_OPENED, booking=self.booking)
        logger.info(
            "Guest page opened for booking %s - guest %s, villa %s",
            self.booking.pk, self.guest.pk, self.villa.pk,
        )
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return self.portal_context(form=GuestRequestForm())


class RequestCreateView(PortalAccessMixin, View):
    """Guest asks for something.

    On success the guest is told the team will *see* this. Not that anyone has
    been messaged - nobody has. The WhatsApp hand-off is
    apps.messaging.tasks.notify_staff_of_request, which is build order step 3
    and still unimplemented, so GuestRequest.notified_at stays null and no
    wording here may imply otherwise. See CLAUDE.md rule 2.
    """

    def get(self, request, *args, **kwargs):
        # Someone reloaded the POST url, or opened it directly.
        return redirect("portal:home", token=kwargs["token"])

    def post(self, request, *args, **kwargs):
        form = GuestRequestForm(request.POST)

        if self.open_requests().count() >= MAX_OPEN_REQUESTS:
            logger.warning(
                "Guest request refused: booking %s already has %s open",
                self.booking.pk, MAX_OPEN_REQUESTS,
            )
            return self.respond(
                request, form,
                error=_("You have a few requests open already. The team is on them."),
            )

        if not form.is_valid():
            return self.respond(request, form)

        guest_request = form.save(commit=False)
        guest_request.organization = self.booking.organization
        guest_request.booking = self.booking
        guest_request.guest = self.guest
        guest_request.save()

        log_activity(
            self.guest,
            GuestActivity.Kind.REQUEST_MADE,
            booking=self.booking,
            subject=guest_request.get_kind_display(),
        )
        logger.info(
            "Guest request %s (%s) made on booking %s by guest %s",
            guest_request.pk, guest_request.kind, self.booking.pk, self.guest.pk,
        )

        return self.respond(request, GuestRequestForm(), sent=True)

    def respond(self, request, form, *, sent=False, error=""):
        if request.htmx:
            return render(
                request, "portal/_request_result.html",
                self.portal_context(form=form, sent=sent, error=error),
            )
        # Without JavaScript the whole page comes back, so the portal still
        # works on a bad connection or an old phone.
        if error:
            return render(
                request, "portal/home.html",
                self.portal_context(form=form, error=error), status=429,
            )
        if not sent:
            return render(
                request, "portal/home.html", self.portal_context(form=form), status=400
            )
        return redirect(f"{reverse('portal:home', kwargs={'token': self.kwargs['token']})}?sent=1")

"""Staff-facing WhatsApp inbox.

Reads and replies to conversations already tracked by this app. Actual
delivery to the BSP (Twilio/360dialog) is apps.messaging.tasks.send_outbound,
which isn't built yet - see the build order in CLAUDE.md, step 3. A reply
here is queued the same way a real send would start, so the UI never claims
a message went out before it actually can.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, View

from apps.bookings.models import Booking
from apps.messaging.models import Conversation, MessageTemplate, OutboundMessage
from apps.organizations.models import Membership
from apps.villas.models import Villa


class ConversationListView(LoginRequiredMixin, ListView):
    template_name = "messaging/inbox.html"
    context_object_name = "conversations"

    def get_queryset(self):
        org = self.request.organization
        if org is None:
            return Conversation.objects.none()

        conversations = list(
            Conversation.objects.filter(organization=org)
            .select_related("guest")
            .prefetch_related("messages", "inbound_messages")
        )

        # A Conversation can be with a guest or with a staff member (see
        # apps.messaging.models.Conversation) - label the latter by name
        # rather than a bare phone number when we can.
        staff_names = dict(
            Membership.objects.filter(organization=org)
            .exclude(user__phone="")
            .values_list("user__phone", "user__full_name")
        )

        guest_ids = [c.guest_id for c in conversations if c.guest_id]
        villa_by_guest = _latest_villa_by_guest(org, guest_ids)

        for conversation in conversations:
            last_outbound = conversation.messages.first()  # OutboundMessage: -created_at
            last_inbound = conversation.inbound_messages.first()  # InboundMessage: -received_at
            candidates = [
                event for event in (
                    _as_timeline_event(last_outbound) if last_outbound else None,
                    {"direction": "in", "body": last_inbound.body, "when": last_inbound.received_at}
                    if last_inbound else None,
                )
                if event is not None
            ]
            conversation.last_message = max(candidates, key=lambda e: e["when"], default=None)
            conversation.staff_label = staff_names.get(conversation.phone)
            conversation.villa = villa_by_guest.get(conversation.guest_id)

        selected_villa = self.request.GET.get("villa", "")
        if selected_villa == "staff":
            conversations = [c for c in conversations if c.guest_id is None]
        elif selected_villa:
            conversations = [c for c in conversations if c.villa and str(c.villa.pk) == selected_villa]

        conversations.sort(
            key=lambda c: c.last_message["when"] if c.last_message else c.created_at,
            reverse=True,
        )
        return conversations

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        context["no_organization"] = org is None
        context["selected_villa"] = self.request.GET.get("villa", "")
        context["villas"] = (
            Villa.objects.filter(organization=org, is_active=True).order_by("name")
            if org else Villa.objects.none()
        )
        return context


class ConversationDetailView(LoginRequiredMixin, DetailView):
    template_name = "messaging/thread.html"
    context_object_name = "conversation"

    def get_queryset(self):
        org = self.request.organization
        return Conversation.objects.filter(organization=org).select_related("guest") if org else Conversation.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["timeline"] = _timeline(self.object)
        context["templates"] = MessageTemplate.objects.filter(
            organization=self.object.organization, is_approved=True,
        )
        villa_by_guest = _latest_villa_by_guest(
            self.object.organization, [self.object.guest_id] if self.object.guest_id else []
        )
        context["villa"] = villa_by_guest.get(self.object.guest_id)
        return context


class SendReplyView(LoginRequiredMixin, View):
    """Queues one outbound message. Free text is only allowed while the
    24-hour service window is open; outside it, an approved template is
    required - see Conversation.window_is_open and CLAUDE.md rule 1.
    """

    def post(self, request, pk):
        org = request.organization
        conversation = get_object_or_404(
            Conversation.objects.filter(organization=org) if org else Conversation.objects.none(),
            pk=pk,
        )

        template = None
        template_id = request.POST.get("template")
        if template_id:
            template = get_object_or_404(MessageTemplate, pk=template_id, organization=org, is_approved=True)

        body = request.POST.get("body", "").strip()

        error = None
        if not conversation.window_is_open and template is None:
            error = _("More than 24 hours since they last messaged - pick an approved template first.")
        elif not body:
            error = _("Write a message before sending.")

        if error:
            return render(request, "messaging/_reply_error.html", {"error": error})

        message = OutboundMessage.objects.create(
            organization=org, conversation=conversation, template=template, body=body,
        )
        response = render(request, "messaging/_reply_success.html", {"message": _as_timeline_event(message)})
        response["HX-Trigger"] = "reply-sent"
        return response


def _latest_villa_by_guest(org, guest_ids: list) -> dict:
    """Which villa each guest's conversation is "about" right now.

    Not stored on Conversation - one Conversation covers every message ever
    exchanged with a phone number (see Conversation.Meta.unique_together), so
    a returning guest who has stayed at two different villas would make a
    stored villa wrong the moment they book a second one. Using the guest's
    latest non-cancelled booking instead means the category always reflects
    their current or most recent stay.
    """
    if not guest_ids or org is None:
        return {}
    bookings = (
        Booking.objects.filter(organization=org, guest_id__in=guest_ids)
        .exclude(status=Booking.Status.CANCELLED)
        .select_related("villa")
        .order_by("guest_id", "-check_in")
    )
    villa_by_guest = {}
    for booking in bookings:
        villa_by_guest.setdefault(booking.guest_id, booking.villa)
    return villa_by_guest


def _timeline(conversation):
    """Both directions, oldest first, as plain dicts so the template doesn't
    need to know it's looking at two different models.
    """
    events = [_as_timeline_event(m) for m in conversation.messages.all()]
    events += [
        {"direction": "in", "body": m.body, "when": m.received_at}
        for m in conversation.inbound_messages.all()
    ]
    events.sort(key=lambda e: e["when"])
    return events


def _as_timeline_event(message: OutboundMessage) -> dict:
    return {
        "direction": "out",
        "body": message.body,
        # sent_at is when it actually went out; a still-queued message has no
        # sent_at yet, so it sorts by when it was queued instead.
        "when": message.sent_at or message.created_at,
        "status": message.status,
        "status_display": message.get_status_display(),
        "error": message.error,
    }

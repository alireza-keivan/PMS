"""Staff-facing WhatsApp inbox.

This is for conversations between staff/manager/owner and clients - not
staff talking to each other. Conversation also backs internal staff alerts
(see apps.messaging.models.Conversation), but those don't belong on this
screen, so every view here is scoped to conversations that have a guest.

Reads and replies to conversations already tracked by this app. Actual
delivery to the BSP (Twilio/360dialog) is apps.messaging.tasks.send_outbound,
which isn't built yet - see the build order in CLAUDE.md, step 3. A reply
here is queued the same way a real send would start, so the UI never claims
a message went out before it actually can.

Layout: one page, two panes (see templates/messaging/inbox.html) - the
conversation list never navigates away, it loads the selected thread into
the right pane in place. `ConversationDetailView` therefore renders two
different things depending on how it's reached: an HTMX request from a list
row gets just the thread pane back; a plain GET (a bookmarked link, a page
refresh) gets the whole shell with that thread already open, so the URL
stays shareable.
"""

import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, View

from apps.bookings.models import Booking
from apps.messaging.models import Conversation, MessageTemplate, OutboundMessage
from apps.organizations.scoping import scoped_villas


class ConversationListView(LoginRequiredMixin, ListView):
    context_object_name = "conversations"

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data()
        template = "messaging/_conversation_list.html" if request.htmx else "messaging/inbox.html"
        return render(request, template, context)

    def get_queryset(self):
        return _visible_conversations(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_list_panel_context(self.request))
        context["active_id"] = None
        return context


class ConversationDetailView(LoginRequiredMixin, DetailView):
    template_name = "messaging/_thread_panel.html"
    context_object_name = "conversation"

    def get_queryset(self):
        return _scoped_conversations(self.request)

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        context = self.get_context_data(object=self.object)

        if request.htmx:
            return self.render_to_response(context)

        # A direct visit (bookmark, refresh, shared link) gets the full
        # two-pane shell with this thread already open, not a bare fragment.
        context.update(_list_panel_context(request))
        context["conversations"] = _visible_conversations(request)
        context["active_id"] = self.object.pk
        context["active_conversation"] = self.object
        return render(request, "messaging/inbox.html", context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conversation = self.object

        status, booking = _guest_status_by_guest(
            conversation.organization, [conversation.guest_id]
        ).get(conversation.guest_id, ("", None))

        context["status_label"] = _STATUS_LABELS.get(status)
        context["status_tag_class"] = _STATUS_TAG_CLASS.get(status, "tag-neutral")
        context["groups"] = _grouped_timeline(conversation)
        context["booking"] = booking
        context["templates"] = _fillable_templates(conversation, booking.villa if booking else None)
        return context


class SendReplyView(LoginRequiredMixin, View):
    """Queues one outbound message. Free text is only allowed while the
    24-hour service window is open; outside it, an approved template is
    required - see Conversation.window_is_open and CLAUDE.md rule 1.
    """

    def post(self, request, pk):
        org = request.organization
        conversation = get_object_or_404(_scoped_conversations(request), pk=pk)

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
        group = _message_group([_as_timeline_event(message)])
        status, booking = _guest_status_by_guest(org, [conversation.guest_id]).get(
            conversation.guest_id, ("", None)
        )
        row = _conversation_row(conversation, booking.villa if booking else None, status)
        response = render(
            request, "messaging/_reply_success.html", {"group": group, "row": row},
        )
        response["HX-Trigger"] = "reply-sent"
        return response


_STATUS_LABELS = {
    "arriving": _("Arriving"),
    "checked_in": _("Checked in"),
    "checked_out": _("Checked out"),
}
_STATUS_TAG_CLASS = {
    "arriving": "tag-accent-2",
    "checked_in": "tag-accent",
    "checked_out": "tag-neutral",
}


def _scoped_conversations(request):
    """Conversations for guests whose *current* stay - the same one
    `_guest_status_by_guest` picks to show in the thread header - is at a
    villa this user may see.

    Deliberately not "any booking this guest has ever had at a scoped
    villa": a repeat guest can have stayed at several of an operator's
    villas over time, and one WhatsApp number is one Conversation for their
    whole history with the business (see Conversation.phone). Scoping by any
    past villa would hand a Bamboo Loft Canggu staff member a guest's entire
    thread - including messages about a stay at a villa they have nothing to
    do with - just because that guest happened to stay at Bamboo Loft Canggu
    once. Scoping by the current/next/most-recent booking instead keeps
    staff seeing exactly the guest relationship the UI already shows them.
    """
    org = request.organization
    if org is None:
        return Conversation.objects.none()
    villas, _membership = scoped_villas(request)
    villa_ids = {v.id for v in villas}

    all_guest_ids = list(
        Conversation.objects.filter(organization=org, guest__isnull=False)
        .values_list("guest_id", flat=True)
        .distinct()
    )
    status_by_guest = _guest_status_by_guest(org, all_guest_ids)
    visible_guest_ids = [
        guest_id
        for guest_id, (_status, booking) in status_by_guest.items()
        if booking and booking.villa_id in villa_ids
    ]
    return (
        Conversation.objects.filter(organization=org, guest_id__in=visible_guest_ids)
        .select_related("guest")
    )


def _visible_conversations(request):
    org = request.organization
    if org is None:
        return []

    conversations = list(
        _scoped_conversations(request).prefetch_related("messages", "inbound_messages")
    )

    guest_ids = [c.guest_id for c in conversations]
    status_by_guest = _guest_status_by_guest(org, guest_ids)

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
        # There's no read/unread tracking on the model - a conversation reads
        # as unread when the last thing that happened is the guest talking
        # and staff hasn't replied since, not a stored flag.
        conversation.unread = bool(conversation.last_message) and conversation.last_message["direction"] == "in"
        status, booking = status_by_guest.get(conversation.guest_id, ("", None))
        conversation.villa = booking.villa if booking else None
        conversation.status = status

    filter_value = request.GET.get("filter", "all")
    if filter_value.startswith("status:"):
        wanted = filter_value[len("status:"):]
        conversations = [c for c in conversations if c.status == wanted]
    elif filter_value.startswith("villa:"):
        wanted = filter_value[len("villa:"):]
        conversations = [c for c in conversations if c.villa and str(c.villa.pk) == wanted]

    query = request.GET.get("q", "").strip().lower()
    if query:
        def matches(c):
            if query in c.guest.full_name.lower():
                return True
            return (
                any(query in m.body.lower() for m in c.messages.all())
                or any(query in m.body.lower() for m in c.inbound_messages.all())
            )
        conversations = [c for c in conversations if matches(c)]

    conversations.sort(
        key=lambda c: c.last_message["when"] if c.last_message else c.created_at,
        reverse=True,
    )
    return conversations


def _list_panel_context(request):
    org = request.organization
    filter_value = request.GET.get("filter", "all")
    query = request.GET.get("q", "")

    villas = scoped_villas(request)[0] if org else []
    return {
        "no_organization": org is None,
        "filter_value": filter_value,
        "q": query,
        "status_options": [
            {"value": f"status:{key}", "label": label} for key, label in _STATUS_LABELS.items()
        ],
        "villa_options": [{"value": f"villa:{v.pk}", "label": v.name} for v in villas],
    }


def _guest_status_by_guest(org, guest_ids: list) -> dict:
    """For each guest: ("arriving" | "checked_in" | "checked_out", booking) -
    not stored on Conversation, worked out fresh from their bookings. The
    booking is whichever one the status/villa/room/dates shown in the thread
    header should come from.

    "Arriving" means their stay hasn't started yet, "checked in" means a stay
    is in progress right now, and "checked out" means every booking they've
    ever had with us has already ended. A guest can rack up many bookings
    over time (past and future at once), so this isn't "their latest
    booking" - it's whichever booking is happening now, or the next one
    coming up, or failing both the most recent one that already ended.
    """
    if not guest_ids or org is None:
        return {}
    today = timezone.localdate()
    bookings = (
        Booking.objects.filter(organization=org, guest_id__in=guest_ids)
        .exclude(status=Booking.Status.CANCELLED)
        .select_related("villa", "room")
        .order_by("guest_id", "check_in")
    )
    bookings_by_guest = {}
    for booking in bookings:
        bookings_by_guest.setdefault(booking.guest_id, []).append(booking)

    result = {}
    for guest_id, guest_bookings in bookings_by_guest.items():
        current = next((b for b in guest_bookings if b.check_in <= today < b.check_out), None)
        if current:
            result[guest_id] = ("checked_in", current)
            continue
        upcoming = next((b for b in guest_bookings if b.check_in > today), None)
        if upcoming:
            result[guest_id] = ("arriving", upcoming)
            continue
        most_recent = guest_bookings[-1]  # sorted ascending by check_in
        result[guest_id] = ("checked_out", most_recent)
    return result


def _as_timeline_event(message: OutboundMessage) -> dict:
    return {
        "direction": "out",
        "body": message.body,
        # sent_at is when it actually went out; a still-queued message has no
        # sent_at yet, so it sorts by when it was queued instead.
        "when": message.sent_at or message.created_at,
        "status_display": message.get_status_display(),
        "error": message.error,
    }


def _grouped_timeline(conversation):
    """Both directions, oldest first, consecutive same-sender messages
    collapsed into one group - one timestamp and (for staff messages) one
    delivery-status word per group, shown once on the group's last message,
    matching the design (see design_handoff_messages/README.md).
    """
    events = [_as_timeline_event(m) for m in conversation.messages.all()]
    events += [
        {"direction": "in", "body": m.body, "when": m.received_at}
        for m in conversation.inbound_messages.all()
    ]
    events.sort(key=lambda e: e["when"])

    groups = []
    for event in events:
        if groups and groups[-1]["direction"] == event["direction"]:
            groups[-1]["events"].append(event)
        else:
            groups.append({"direction": event["direction"], "events": [event]})
    return [_message_group(g["events"]) for g in groups]


def _message_group(events):
    direction = events[0]["direction"]
    last = events[-1]
    return {
        "direction": direction,
        "messages": events,
        "time": last["when"],
        "delivery_status": last.get("status_display") if direction == "out" else None,
        "error": last.get("error") if direction == "out" else None,
    }


def _conversation_row(conversation, villa, status):
    """Everything one conversation-list row needs to render - used for the
    full list and for the single-row out-of-band refresh after a reply.
    """
    last_outbound = conversation.messages.first()
    last_inbound = conversation.inbound_messages.first()
    candidates = [
        event for event in (
            _as_timeline_event(last_outbound) if last_outbound else None,
            {"direction": "in", "body": last_inbound.body, "when": last_inbound.received_at}
            if last_inbound else None,
        )
        if event is not None
    ]
    last_message = max(candidates, key=lambda e: e["when"], default=None)
    conversation.last_message = last_message
    conversation.unread = bool(last_message) and last_message["direction"] == "in"
    conversation.villa = villa
    conversation.status = status
    return conversation


def _fillable_templates(conversation, villa):
    """Approved templates for this conversation's org, with {{1}} (guest name)
    and {{2}} (villa) already substituted where we know them. Any further
    placeholder ({{3}}, {{4}}...) has no fixed meaning beyond that, so it's
    left as-is for staff to fill in by hand.
    """
    guest_name = conversation.guest.full_name if conversation.guest else ""
    villa_name = villa.name if villa else ""

    def fill(body: str) -> str:
        filled = body
        if guest_name:
            filled = filled.replace("{{1}}", guest_name)
        if villa_name:
            filled = filled.replace("{{2}}", villa_name)
        return filled

    templates = MessageTemplate.objects.filter(organization=conversation.organization, is_approved=True)
    result = []
    for t in templates:
        body = fill(t.body_id if t.language == "id" else t.body_en)
        result.append({
            "pk": t.pk,
            "name": t.name,
            "language": t.language,
            "body": body,
            # Rendered as an HTML attribute value (hx-vals) inside a
            # single-quoted attribute - Django's autoescape turns the JSON's
            # double quotes into `&quot;`, which the browser decodes back to
            # `"` before htmx parses it, so this round-trips safely.
            "vals_json": json.dumps({"template": t.pk, "body": body}),
        })
    return result

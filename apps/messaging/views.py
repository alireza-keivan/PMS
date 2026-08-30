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
"""

from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, View

from apps.bookings.models import Booking
from apps.messaging.models import Conversation, MessageTemplate, OutboundMessage
from apps.villas.models import Villa


class ConversationListView(LoginRequiredMixin, ListView):
    template_name = "messaging/inbox.html"
    context_object_name = "conversations"

    def get_queryset(self):
        org = self.request.organization
        if org is None:
            return Conversation.objects.none()

        conversations = list(
            Conversation.objects.filter(organization=org, guest__isnull=False)
            .select_related("guest")
            .prefetch_related("messages", "inbound_messages")
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
            status, villa = status_by_guest.get(conversation.guest_id, ("", None))
            conversation.villa = villa
            conversation.guest_status = status

        selected_villa = self.request.GET.get("villa", "")
        if selected_villa:
            conversations = [c for c in conversations if c.villa and str(c.villa.pk) == selected_villa]

        # A guest still to arrive or currently staying counts as "checked
        # in" - only someone whose every booking has already ended counts as
        # "checked out". That's the default view: who's still ours to serve.
        status = self.request.GET.get("status", "checked_in")
        if status in ("checked_in", "checked_out"):
            conversations = [c for c in conversations if c.guest_status == status]

        if self.request.GET.get("recent") == "1":
            cutoff = timezone.now() - timedelta(hours=24)
            conversations = [
                c for c in conversations if c.last_message and c.last_message["when"] >= cutoff
            ]

        conversations.sort(
            key=lambda c: c.last_message["when"] if c.last_message else c.created_at,
            reverse=True,
        )
        return conversations

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        context["no_organization"] = org is None

        selected_villa = self.request.GET.get("villa", "")
        status = self.request.GET.get("status", "checked_in")
        recent_only = self.request.GET.get("recent") == "1"

        villas = (
            Villa.objects.filter(organization=org).live().order_by("name")
            if org else Villa.objects.none()
        )
        context["villa_tabs"] = (
            [{"label": _("All villas"), "href": _tab_href(self.request, villa=None), "active": not selected_villa}]
            + [
                {
                    "label": v.name,
                    "href": _tab_href(self.request, villa=str(v.pk)),
                    "active": selected_villa == str(v.pk),
                }
                for v in villas
            ]
        )
        context["status_tabs"] = [
            {"label": _("Checked in"), "href": _tab_href(self.request, status=None), "active": status == "checked_in"},
            {
                "label": _("Checked out"), "href": _tab_href(self.request, status="checked_out"),
                "active": status == "checked_out",
            },
            {"label": _("All guests"), "href": _tab_href(self.request, status="all"), "active": status == "all"},
        ]
        context["recent_toggle"] = {
            "label": _("Last 24 hours"),
            "href": _tab_href(self.request, recent=None if recent_only else "1"),
            "active": recent_only,
        }
        context["is_filtered"] = bool(selected_villa) or status != "checked_in" or recent_only
        return context


class ConversationDetailView(LoginRequiredMixin, DetailView):
    template_name = "messaging/thread.html"
    context_object_name = "conversation"

    def get_queryset(self):
        org = self.request.organization
        return (
            Conversation.objects.filter(organization=org, guest__isnull=False).select_related("guest")
            if org else Conversation.objects.none()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conversation = self.object

        _status, villa = _guest_status_by_guest(
            conversation.organization, [conversation.guest_id]
        ).get(conversation.guest_id, ("", None))

        context["timeline"] = _timeline(conversation)
        context["villa"] = villa
        context["templates"] = _fillable_templates(conversation, villa)
        return context


class SendReplyView(LoginRequiredMixin, View):
    """Queues one outbound message. Free text is only allowed while the
    24-hour service window is open; outside it, an approved template is
    required - see Conversation.window_is_open and CLAUDE.md rule 1.
    """

    def post(self, request, pk):
        org = request.organization
        conversation = get_object_or_404(
            Conversation.objects.filter(organization=org, guest__isnull=False) if org else Conversation.objects.none(),
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


def _tab_href(request, **overrides) -> str:
    """Current query string with the given params replaced, so switching one
    filter (villa, status, recency) never resets the others.
    """
    params = request.GET.copy()
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    query = params.urlencode()
    return f"?{query}" if query else "?"


def _guest_status_by_guest(org, guest_ids: list) -> dict:
    """For each guest: ("checked_in" | "checked_out", villa) - not stored on
    Conversation, worked out fresh from their bookings.

    "Checked in" means still ours to serve: a stay in progress right now, or
    one still to come. "Checked out" means every booking they've ever had
    with us has already ended - there's nothing left on the books. A guest
    can rack up many bookings over time (past and future at once), so this
    isn't "their latest booking" - it's whether *any* booking hasn't ended
    yet, checked against the earliest one that hasn't, so the villa shown is
    whichever stay is current or coming up next.
    """
    if not guest_ids or org is None:
        return {}
    today = timezone.localdate()
    bookings = (
        Booking.objects.filter(organization=org, guest_id__in=guest_ids)
        .exclude(status=Booking.Status.CANCELLED)
        .select_related("villa")
        .order_by("guest_id", "check_in")
    )
    bookings_by_guest = {}
    for booking in bookings:
        bookings_by_guest.setdefault(booking.guest_id, []).append(booking)

    result = {}
    for guest_id, guest_bookings in bookings_by_guest.items():
        current_or_upcoming = next((b for b in guest_bookings if b.check_out > today), None)
        if current_or_upcoming:
            result[guest_id] = ("checked_in", current_or_upcoming.villa)
        else:
            most_recent = guest_bookings[-1]  # sorted ascending by check_in
            result[guest_id] = ("checked_out", most_recent.villa)
    return result


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
    return [
        {
            "pk": t.pk,
            "name": t.name,
            "language": t.language,
            "body": fill(t.body_id if t.language == "id" else t.body_en),
        }
        for t in templates
    ]

"""window_is_open is what decides whether an outbound WhatsApp message can be
free-form text or must go through an approved template. Getting this wrong
means a rejected message at best, a policy violation at worst - see CLAUDE.md
rule 1.
"""

from datetime import timedelta

from django.utils import timezone

from apps.messaging.models import Conversation, OutboundMessage


def test_window_is_open_within_24_hours_of_last_inbound_message(org):
    convo = Conversation.objects.create(
        organization=org, phone="+6281234567890",
        last_inbound_at=timezone.now() - timedelta(hours=1),
    )
    assert convo.window_is_open is True


def test_window_is_closed_after_24_hours(org):
    convo = Conversation.objects.create(
        organization=org, phone="+6281234567890",
        last_inbound_at=timezone.now() - timedelta(hours=25),
    )
    assert convo.window_is_open is False


def test_window_is_closed_when_guest_has_never_messaged_us(org):
    convo = Conversation.objects.create(organization=org, phone="+6281234567890")
    assert convo.window_is_open is False


def test_outbound_message_defaults_to_queued(org):
    convo = Conversation.objects.create(organization=org, phone="+6281234567890")
    message = OutboundMessage.objects.create(organization=org, conversation=convo, body="Hi!")
    assert message.status == OutboundMessage.Status.QUEUED

"""WhatsApp, through the official Cloud API.

Two constraints shape everything in this app:

  1. Only the official WhatsApp Business Platform, via a BSP (Twilio,
     360dialog). Never a library that drives a WhatsApp Web session - that
     breaks WhatsApp's terms and gets the client's number banned.

  2. Outside a 24-hour window since the person last messaged us, only a
     pre-approved template may be sent. Free-form text will be rejected. Both
     the window and the template are modelled here rather than discovered at
     send time.
"""

from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel


class MessageTemplate(TenantOwnedModel):
    """A template approved by WhatsApp, required outside the 24-hour window.

    Approval happens in the BSP's console, not here. `is_approved` mirrors that
    state; sending against an unapproved template will fail upstream.
    """

    name = models.CharField(max_length=120, help_text=_("Name registered with WhatsApp."))
    language = models.CharField(max_length=5, default="en")
    body_en = models.TextField()
    body_id = models.TextField(blank=True)
    is_approved = models.BooleanField(default=False)

    class Meta:
        unique_together = [("organization", "name", "language")]

    def __str__(self):
        return f"{self.name} ({self.language})"


class Conversation(TenantOwnedModel):
    """Tracks the 24-hour service window per phone number."""

    phone = models.CharField(max_length=32, db_index=True)
    guest = models.ForeignKey(
        "guests.Guest", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="conversations",
    )
    last_inbound_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("organization", "phone")]

    @property
    def window_is_open(self) -> bool:
        """Whether free-form text is currently allowed to this number."""
        if not self.last_inbound_at:
            return False
        return timezone.now() - self.last_inbound_at < timedelta(hours=24)


class InboundMessage(TenantOwnedModel):
    """A message the guest or staff member actually sent us.

    Kept as its own model rather than folding into OutboundMessage with a
    `direction` flag - delivery status, templates and provider errors only
    ever apply to what we send, so a shared table would carry a pile of
    columns that are always null on one side.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="inbound_messages"
    )
    body = models.TextField()
    provider_message_id = models.CharField(max_length=120, blank=True)
    # Separate from created_at (row-creation audit trail) because a webhook
    # delivery can lag behind when the provider says the message actually
    # arrived - same split OutboundMessage makes between created_at and sent_at.
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.conversation.phone}: {self.body[:40]}"


class OutboundMessage(TenantOwnedModel):
    """One message queued for delivery.

    Queued rather than sent inline so a provider outage delays a notification
    instead of failing the guest's request in the browser.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", _("Waiting to send")
        SENT = "sent", _("Sent")
        DELIVERED = "delivered", _("Delivered")
        FAILED = "failed", _("Failed")

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    template = models.ForeignKey(
        MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True
    )
    body = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    provider_message_id = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

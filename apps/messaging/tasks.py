"""Outbound WhatsApp delivery.

Staff notification is the point of this app: when a guest asks for something in
the portal, a message goes to the responsible person's phone. A dashboard row
nobody looks at is not a notification. See CLAUDE.md rule 1.
"""

from celery import shared_task


@shared_task
def notify_staff_of_request(request_id: int) -> None:
    """Message the assigned staff member about a new guest request.

    Staff conversations are usually inside the 24-hour window; fall back to an
    approved template when they are not.
    """
    raise NotImplementedError("Build order step 3.")


@shared_task
def send_outbound(message_id: int) -> None:
    """Deliver one queued message through the configured BSP."""
    raise NotImplementedError("Build order step 3.")

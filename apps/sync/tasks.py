"""Scheduled ingestion.

Webhooks are the primary path on the premium tier, but they get lost, so a
periodic reconciliation pull runs regardless. On the basic tier polling is the
only path available.
"""

from celery import shared_task


@shared_task
def reconcile_beds24(account_id: int) -> None:
    """Re-pull recent Beds24 bookings to catch anything a webhook missed."""
    raise NotImplementedError("Build order step 1.")


@shared_task
def poll_ical_feeds() -> None:
    """Refresh every active iCal feed. Hourly is plenty - OTAs update slower."""
    raise NotImplementedError("Build order step 1.")

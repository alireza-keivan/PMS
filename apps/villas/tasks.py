"""Housekeeping for the villa form.

Only one job so far: clearing up pictures that were picked on a form and then
never saved. See PhotoQuerySet in models.py for why those rows exist at all.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.villas.models import RoomCategoryPhoto, VillaPhoto

logger = logging.getLogger(__name__)

# How long a half-finished edit is left alone before it is tidied away. Long
# enough that somebody who wandered off for lunch mid-edit still comes back to
# their pictures; short enough that abandoned uploads don't pile up in storage.
STALE_AFTER = timedelta(days=1)


@shared_task
def prune_staged_photos() -> dict:
    """Throw away picture changes nobody ever saved.

    Two kinds of leftover, and they are cleared in opposite directions:
      - an upload that was never saved is deleted, because it never became one
        of the villa's pictures in the first place
      - a picture marked for removal that was never saved has that mark taken
        off, because the villa really does still have it

    Either way the villa ends up exactly as it was before the abandoned edit.
    """
    cutoff = timezone.now() - STALE_AFTER
    result = {}

    for model, label in ((VillaPhoto, "villa"), (RoomCategoryPhoto, "room type")):
        dropped = 0
        for photo in model.objects.filter(is_pending=True, updated_at__lt=cutoff):
            photo.delete()
            dropped += 1
        restored = model.objects.filter(
            pending_delete=True, updated_at__lt=cutoff,
        ).update(pending_delete=False)

        result[label] = {"dropped": dropped, "restored": restored}
        if dropped or restored:
            logger.info(
                "Cleared abandoned %s picture edits - %s upload(s) dropped, %s put back",
                label, dropped, restored,
            )

    return result

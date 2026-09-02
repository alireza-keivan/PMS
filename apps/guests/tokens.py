"""Signed links for guest portal access.

No account, no password. The link carries the booking reference, signed with
the project SECRET_KEY and expiring on its own - so a leaked or forwarded link
stops working after the stay rather than granting indefinite access.

The signature proves which booking the visitor holds a link for; it is not a
login. Never expose anything beyond that booking's own data behind it.

There are two locks on the door, and both have to open:

  1. The signature, checked by `read_token` - proves the link came from us and
     is younger than GUEST_LINK_MAX_AGE_DAYS.
  2. The stay itself, checked by `resolve_booking` - the link only works around
     the dates the guest is actually here. A link forwarded to a friend, or
     found in an old chat months later, opens nothing.

Lock 2 is what makes the "no login" decision safe. Without it a link would keep
working for its full signed lifetime no matter who ended up holding it.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

_signer = TimestampSigner(salt="guest-portal")

# How far either side of the stay the page stays open. A day early so a guest
# can look at it on the plane, a day late so a checkout-morning request still
# goes through.
PORTAL_OPENS_DAYS_BEFORE = 1
PORTAL_CLOSES_DAYS_AFTER = 1


def make_token(booking) -> str:
    return _signer.sign(str(booking.reference))


def portal_url(booking, base_url: str = "") -> str:
    path = reverse("portal:home", kwargs={"token": make_token(booking)})
    return f"{base_url}{path}"


def read_token(token: str) -> str | None:
    """Return the booking reference, or None if invalid or expired."""
    max_age = settings.GUEST_LINK_MAX_AGE_DAYS * 24 * 60 * 60
    try:
        return _signer.unsign(token, max_age=max_age)
    except SignatureExpired:
        logger.warning("Guest link refused: signature older than %s days", settings.GUEST_LINK_MAX_AGE_DAYS)
        return None
    except BadSignature:
        # Either someone edited a link or someone is guessing at them. Worth a
        # line either way, but never the token itself - a valid one is a key.
        logger.warning("Guest link refused: signature did not check out")
        return None


def portal_window(booking) -> tuple:
    """The first and last day this booking's link opens on."""
    return (
        booking.check_in - timedelta(days=PORTAL_OPENS_DAYS_BEFORE),
        booking.check_out + timedelta(days=PORTAL_CLOSES_DAYS_AFTER),
    )


def resolve_booking(token: str):
    """The booking a guest link opens, or None. Never raises.

    Every rejection returns the same None and the page above shows the same
    "this link doesn't work any more" screen, so the page can never be read
    back as an oracle for which booking references exist.
    """
    # Imported here rather than at module level: bookings.models imports guests
    # indirectly through its own relations, and this module is imported from
    # inside that graph.
    from apps.bookings.models import Booking

    reference = read_token(token)
    if reference is None:
        return None

    booking = (
        Booking.objects.select_related("villa", "guest", "organization")
        .filter(reference=reference)
        .first()
    )
    if booking is None:
        logger.warning("Guest link refused: no booking with that reference")
        return None

    # A calendar-only row from an iCal feed carries dates and nothing else -
    # there is no guest behind it to show a page to.
    if booking.guest_id is None:
        logger.warning("Guest link refused: booking %s has no guest details", booking.pk)
        return None

    if booking.status != Booking.Status.CONFIRMED:
        logger.warning(
            "Guest link refused: booking %s is %s, not a live stay", booking.pk, booking.status
        )
        return None

    opens_on, closes_on = portal_window(booking)
    today = timezone.localdate()
    if not (opens_on <= today <= closes_on):
        logger.warning(
            "Guest link refused: booking %s is open %s to %s, today is %s",
            booking.pk, opens_on, closes_on, today,
        )
        return None

    return booking

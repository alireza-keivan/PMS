"""Signed links for guest portal access.

No account, no password. The link carries the booking reference, signed with
the project SECRET_KEY and expiring on its own - so a leaked or forwarded link
stops working after the stay rather than granting indefinite access.

The signature proves which booking the visitor holds a link for; it is not a
login. Never expose anything beyond that booking's own data behind it.
"""

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.urls import reverse

_signer = TimestampSigner(salt="guest-portal")


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
    except (BadSignature, SignatureExpired):
        return None

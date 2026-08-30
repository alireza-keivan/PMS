"""Small helpers shared across apps - nothing here should depend on any one
app's models.
"""

from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request, fallback_url):
    """POST['next'] if it's a same-site path, else the given fallback URL
    (an already-resolved path, not a URL name - callers that need kwargs,
    e.g. a villa slug, resolve those themselves before calling this).
    Used by the calendar's inline villa/room/booking actions, which all need
    to return to wherever the calendar was (with its date range and search
    intact) rather than a fixed destination.
    """
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return fallback_url

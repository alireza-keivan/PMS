"""Resolves the tenant for each request, and catches people who have none.

`OrganizationMiddleware` sets `request.organization` for authenticated users so
views and querysets have a single, consistent source of scope. Views must still
filter explicitly - this middleware supplies the value, it does not enforce its
use.

`OnboardingMiddleware` handles one specific way that value can be missing: the
person just made an account with Google and belongs to no business at all. They
go to the welcome form to name one. Note the narrowness - somebody who belongs
to a business that has been switched off also has no `request.organization`,
but asking them to create a second business would be wrong, so they keep the
"nothing here yet" state the dashboard screens already render.

Resolved eagerly, not wrapped in SimpleLazyObject: a lazy proxy wrapping None
is not None, so a view checking `if request.organization is None:` - the
natural way to guard a tenant-scoped view - would silently always be False.
One membership lookup per request is cheap enough at this project's scale
that the laziness isn't worth that footgun.
"""

from django.conf import settings
from django.shortcuts import redirect


def _resolve_organization(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None
    membership = (
        user.memberships.select_related("organization")
        .filter(organization__is_active=True)
        .first()
    )
    return membership.organization if membership else None


class OrganizationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organization = _resolve_organization(request)
        return self.get_response(request)


def _strip_language_prefix(path: str) -> str:
    """`/id/accounts/welcome/` -> `/accounts/welcome/`.

    Dashboard URLs carry a language prefix in Indonesian but not in English
    (prefix_default_language=False), so the exempt list is matched against the
    path with any prefix removed - one list, not one per language.
    """
    for code, _name in settings.LANGUAGES:
        prefix = f"/{code}/"
        if path.startswith(prefix):
            return path[len(prefix) - 1 :]
    return path


class OnboardingMiddleware:
    """Sends a brand new account - one with no business at all - to the welcome form.

    Anything that must keep working for a user in that state is exempt, or the
    redirect becomes a trap: the welcome form itself, signing out, the Google
    round trip, the Django admin (a superuser has no membership and shouldn't
    need one), webhooks, the language switcher and static files.
    """

    EXEMPT_PREFIXES = (
        "/accounts/",   # login, logout, and the welcome form itself
        "/admin/",
        "/auth/",       # allauth: the Google round trip
        "/api/",        # webhooks and machine callers - never a browser redirect
        "/i18n/",
        "/stay/",       # guest portal: signed link, no account, no organization
        "/villa/",      # public mini villa sites
        "/__debug__/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._needs_onboarding(request):
            return redirect("accounts:onboarding")
        return self.get_response(request)

    def _needs_onboarding(self, request) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if getattr(request, "organization", None) is not None:
            return False
        path = _strip_language_prefix(request.path_info)
        if path.startswith((settings.STATIC_URL, settings.MEDIA_URL)):
            return False
        if path.startswith(self.EXEMPT_PREFIXES):
            return False
        # Checked last, and only for the handful of people it can apply to:
        # one extra query, never on a normal request.
        return not user.memberships.exists()

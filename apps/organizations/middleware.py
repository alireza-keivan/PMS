"""Resolves the tenant for each request.

Sets `request.organization` for authenticated users so views and querysets have
a single, consistent source of scope. Views must still filter explicitly - this
middleware supplies the value, it does not enforce its use.
"""

from django.utils.functional import SimpleLazyObject


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
        request.organization = SimpleLazyObject(lambda: _resolve_organization(request))
        return self.get_response(request)

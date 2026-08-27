"""request.organization is what every view and template relies on for scoping.
If middleware resolves the wrong organization, or none at all for a logged-in
user, every downstream tenant filter silently does the wrong thing.
"""

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse

from apps.organizations.middleware import OrganizationMiddleware
from apps.organizations.models import Membership


def _run_middleware(request):
    middleware = OrganizationMiddleware(get_response=lambda r: HttpResponse())
    middleware(request)
    return request.organization


def test_anonymous_user_resolves_to_no_organization(rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    assert _run_middleware(request) is None


def test_authenticated_user_resolves_their_organization(rf, org, user):
    Membership.objects.create(user=user, organization=org)
    request = rf.get("/")
    request.user = user
    assert _run_middleware(request) == org


def test_membership_in_inactive_organization_is_ignored(rf, org, user):
    org.is_active = False
    org.save()
    Membership.objects.create(user=user, organization=org)
    request = rf.get("/")
    request.user = user
    assert _run_middleware(request) is None

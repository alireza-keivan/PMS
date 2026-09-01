"""Creating a tenant.

Kept out of the view because more than one place will want it: the welcome
form today, seed data and (later) an invite link all need a business plus its
first Owner created together, or not at all.
"""

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils.text import slugify

from apps.organizations.models import Membership, Organization
from apps.organizations.permissions import MANAGER_GROUP, STAFF_GROUP

logger = logging.getLogger(__name__)


def unique_slug(name: str) -> str:
    """A URL-safe, unused slug for a business name.

    Two operators picking the same name is entirely plausible ("Bali Villas"),
    so collisions get a number rather than an error the person has to solve.
    """
    base = slugify(name)[:40] or "villas"
    slug = base
    suffix = 2
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


@transaction.atomic
def create_organization_for(user, name: str) -> Organization:
    """Create a business and make `user` its Owner.

    Sync tier and plan keep their model defaults - basic calendar links on the
    starter plan. An admin moves a client up from there.
    """
    organization = Organization.objects.create(name=name.strip(), slug=unique_slug(name))
    Membership.objects.create(user=user, organization=organization)
    manager_group, _created = Group.objects.get_or_create(name=MANAGER_GROUP)
    user.groups.add(manager_group)
    logger.info(
        "Organization %s (%s) created by user %s, who is now its owner",
        organization.pk,
        organization.slug,
        user.pk,
    )
    return organization


class EmailAlreadyInUse(Exception):
    """Raised when a manager tries to add staff under an email that already
    has an account.

    Manager-vs-Staff is a Group on the User, not per-organization (see
    apps.organizations.permissions), so letting an existing account - which
    might be a Manager/Owner of its own business elsewhere - be reused as
    Staff here would silently make them a Manager in this organization too.
    Staff accounts are always created fresh from this flow instead.
    """


@transaction.atomic
def create_staff_for(organization: Organization, *, email: str, password: str, full_name: str = "", villas=()) -> "Membership":
    """Create a brand-new Staff account, scoped to `villas`, for `organization`.

    Only ever called by a Manager, from the "add staff" screen - the email and
    password entered there become the staff member's login, since there's no
    invite-by-email flow yet (see apps.accounts).
    """
    User = get_user_model()
    email = User.objects.normalize_email(email.strip())
    if User.objects.filter(email__iexact=email).exists():
        raise EmailAlreadyInUse(email)

    user = User.objects.create_user(email=email, password=password, full_name=full_name.strip())
    membership = Membership.objects.create(user=user, organization=organization)
    membership.villas.set(villas)
    staff_group, _created = Group.objects.get_or_create(name=STAFF_GROUP)
    user.groups.add(staff_group)
    logger.info(
        "Staff account %s created for organization %s (%s), scoped to %d villa(s)",
        user.pk, organization.pk, organization.slug, len(villas),
    )
    return membership


@transaction.atomic
def update_staff_villas(membership: "Membership", villas=()) -> None:
    """Change which villas a Staff membership is scoped to.

    Manager memberships aren't edited through here - a Manager already sees
    every villa in the organization, so a villa picker has nothing to do.
    """
    membership.villas.set(villas)

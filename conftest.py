"""Shared fixtures for the whole test suite.

Two organizations exist in almost every fixture set on purpose: the single
most important guarantee in this codebase is that data from one never leaks
into the other, so most test files exercise that directly rather than trusting
it by convention.
"""

import pytest
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.guests.models import Guest
from apps.organizations.models import Membership, Organization
from apps.organizations.permissions import MANAGER_GROUP, STAFF_GROUP
from apps.villas.models import Villa


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Canggu Villas", slug="canggu", sync_tier="premium")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Ubud Retreats", slug="ubud", sync_tier="basic")


@pytest.fixture
def villa(org):
    return Villa.objects.create(organization=org, name="Villa Melati", slug="melati")


@pytest.fixture
def user(db):
    return User.objects.create_user(email="staff@example.com", password="testpass123")


@pytest.fixture
def user_without_active_organization(db):
    """Belongs to a business that has been switched off.

    Not the same as a brand new account with no business at all - that one is
    sent to the welcome form by apps.organizations.middleware and never reaches
    a dashboard screen. This user is who the "nothing here yet" states are for.
    """
    user = User.objects.create_user(email="nobody@example.com", password="testpass123")
    switched_off = Organization.objects.create(name="Closed Villas", slug="closed", is_active=False)
    Membership.objects.create(user=user, organization=switched_off)
    return user


@pytest.fixture
def guest(org):
    return Guest.objects.create(organization=org, full_name="Wayan Guest", email="wayan@example.com")


@pytest.fixture
def make_membership(db):
    """Creates a Membership and puts its user in the right group in one call,
    since Manager-vs-Staff is a django.contrib.auth.Group, not a field on
    Membership - see apps.organizations.permissions.
    """
    def _make(user, organization, manager=True):
        membership = Membership.objects.create(user=user, organization=organization)
        group_name = MANAGER_GROUP if manager else STAFF_GROUP
        group, _created = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        return membership
    return _make

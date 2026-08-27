"""Shared fixtures for the whole test suite.

Two organizations exist in almost every fixture set on purpose: the single
most important guarantee in this codebase is that data from one never leaks
into the other, so most test files exercise that directly rather than trusting
it by convention.
"""

import pytest

from apps.accounts.models import User
from apps.guests.models import Guest
from apps.organizations.models import Organization
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
def guest(org):
    return Guest.objects.create(organization=org, full_name="Wayan Guest", email="wayan@example.com")

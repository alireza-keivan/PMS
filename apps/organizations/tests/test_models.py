"""Organization.has_live_sync is the switch every honesty-about-freshness UI
rule depends on, and Membership.can_see_money is what keeps staff away from
figures they shouldn't see. Both get tested directly rather than assumed.
"""

import pytest
from django.db import IntegrityError

from apps.organizations.models import Membership, Organization


def test_premium_tier_has_live_sync(org):
    assert org.sync_tier == Organization.SyncTier.PREMIUM
    assert org.has_live_sync is True


def test_basic_tier_does_not_have_live_sync(other_org):
    assert other_org.sync_tier == Organization.SyncTier.BASIC
    assert other_org.has_live_sync is False


@pytest.mark.parametrize(
    "role,expected",
    [
        (Membership.Role.OWNER, True),
        (Membership.Role.MANAGER, True),
        (Membership.Role.STAFF, False),
    ],
)
def test_can_see_money_by_role(org, user, role, expected):
    membership = Membership.objects.create(user=user, organization=org, role=role)
    assert membership.can_see_money is expected


def test_one_user_cannot_have_two_memberships_in_same_org(org, user):
    Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=user, organization=org, role=Membership.Role.MANAGER)


def test_staff_membership_can_be_scoped_to_specific_villas(org, user, villa):
    membership = Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)
    membership.villas.add(villa)
    assert list(membership.villas.all()) == [villa]

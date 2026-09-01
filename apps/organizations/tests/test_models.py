"""Organization.has_live_sync is the switch every honesty-about-freshness UI
rule depends on, and apps.organizations.permissions.can_see_money is what
keeps staff away from figures they shouldn't see. Both get tested directly
rather than assumed.
"""

import pytest
from django.db import IntegrityError

from apps.organizations.models import Membership, Organization
from apps.organizations.permissions import can_see_money


def test_premium_tier_has_live_sync(org):
    assert org.sync_tier == Organization.SyncTier.PREMIUM
    assert org.has_live_sync is True


def test_basic_tier_does_not_have_live_sync(other_org):
    assert other_org.sync_tier == Organization.SyncTier.BASIC
    assert other_org.has_live_sync is False


@pytest.mark.parametrize("manager,expected", [(True, True), (False, False)])
def test_can_see_money_by_group(org, user, make_membership, manager, expected):
    make_membership(user, org, manager=manager)
    assert can_see_money(user) is expected


def test_one_user_cannot_have_two_memberships_in_same_org(org, user):
    Membership.objects.create(user=user, organization=org)
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=user, organization=org)


def test_staff_membership_can_be_scoped_to_specific_villas(org, user, villa, make_membership):
    membership = make_membership(user, org, manager=False)
    membership.villas.add(villa)
    assert list(membership.villas.all()) == [villa]

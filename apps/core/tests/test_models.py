"""The tenancy backbone. If this file is wrong, every app built on top of
TenantOwnedModel inherits the bug silently.
"""

from datetime import date

import pytest
from django.db import IntegrityError

from apps.core.calendar import BaliHoliday
from apps.villas.models import Villa


def test_tenant_manager_scopes_to_one_organization(org, other_org):
    Villa.objects.create(organization=org, name="Villa A", slug="a")
    Villa.objects.create(organization=other_org, name="Villa B", slug="b")

    assert Villa.objects.count() == 2
    assert Villa.objects.for_organization(org).count() == 1
    assert Villa.objects.for_organization(org).get().name == "Villa A"


def test_for_request_scopes_by_request_organization(org, other_org, rf):
    Villa.objects.create(organization=org, name="Villa A", slug="a")
    Villa.objects.create(organization=other_org, name="Villa B", slug="b")

    request = rf.get("/")
    request.organization = org
    result = Villa.objects.for_request(request)
    assert list(result) == list(Villa.objects.filter(organization=org))


def test_bali_holiday_is_not_tenant_scoped():
    """Holidays apply to the whole island, not one operator - no organization field."""
    assert not hasattr(BaliHoliday, "organization")


def test_bali_holiday_unique_per_name_and_date(db):
    BaliHoliday.objects.create(name="Nyepi", date=date(2026, 3, 19), impact=BaliHoliday.Impact.SHUTDOWN)
    with pytest.raises(IntegrityError):
        BaliHoliday.objects.create(name="Nyepi", date=date(2026, 3, 19))

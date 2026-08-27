import pytest
from django.db import IntegrityError

from apps.villas.models import Amenity, Villa, VillaPhoto


def test_villa_slug_is_unique_per_organization_not_globally(org, other_org):
    """Two different owners can each have a villa at the same URL slug."""
    Villa.objects.create(organization=org, name="Villa Melati", slug="melati")
    Villa.objects.create(organization=other_org, name="Also Melati", slug="melati")
    assert Villa.objects.filter(slug="melati").count() == 2


def test_same_organization_cannot_reuse_a_slug(org):
    Villa.objects.create(organization=org, name="Villa A", slug="melati")
    with pytest.raises(IntegrityError):
        Villa.objects.create(organization=org, name="Villa B", slug="melati")


def test_amenity_is_shared_across_organizations(org, other_org):
    """One Amenity row, linked from villas owned by different organizations."""
    pool = Amenity.objects.create(name_en="Pool", name_id="Kolam renang")
    villa_a = Villa.objects.create(organization=org, name="Villa A", slug="a")
    villa_b = Villa.objects.create(organization=other_org, name="Villa B", slug="b")

    pool.villas.add(villa_a, villa_b)

    assert Amenity.objects.count() == 1
    assert set(pool.villas.all()) == {villa_a, villa_b}


def test_villa_photos_are_ordered_by_sort_order(villa):
    third = VillaPhoto.objects.create(villa=villa, organization=villa.organization, sort_order=2)
    first = VillaPhoto.objects.create(villa=villa, organization=villa.organization, sort_order=0)
    second = VillaPhoto.objects.create(villa=villa, organization=villa.organization, sort_order=1)

    assert list(villa.photos.all()) == [first, second, third]

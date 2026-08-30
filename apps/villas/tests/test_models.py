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


def test_a_shared_amenity_is_one_row_used_by_every_organization(org, other_org):
    """The built-in amenities belong to nobody, so two operators' room types
    point at the same row rather than each getting their own copy of "Pool".
    """
    pool = Amenity.objects.get(name_en="Pool", organization=None)
    villa_a = Villa.objects.create(organization=org, name="Villa A", slug="a")
    villa_b = Villa.objects.create(organization=other_org, name="Villa B", slug="b")

    villa_a.room_categories.first().amenities.add(pool)
    villa_b.room_categories.first().amenities.add(pool)

    assert Amenity.objects.filter(name_en="Pool").count() == 1
    assert {c.villa for c in pool.room_categories.all()} == {villa_a, villa_b}


def test_a_custom_amenity_is_only_offered_back_to_who_made_it(org, other_org):
    mine = Amenity.objects.create(name_en="Yoga deck", name_id="Yoga deck", organization=org)

    assert mine in Amenity.available_to(org)
    assert mine not in Amenity.available_to(other_org)
    # and the shared ones are still there alongside it
    assert Amenity.available_to(org).filter(name_en="Pool").exists()


def test_villa_photos_are_ordered_by_sort_order(villa):
    third = VillaPhoto.objects.create(villa=villa, organization=villa.organization, sort_order=2)
    first = VillaPhoto.objects.create(villa=villa, organization=villa.organization, sort_order=0)
    second = VillaPhoto.objects.create(villa=villa, organization=villa.organization, sort_order=1)

    assert list(villa.photos.all()) == [first, second, third]

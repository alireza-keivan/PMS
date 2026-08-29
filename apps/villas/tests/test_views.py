"""The villa picker is the first thing anyone sees after logging in, and the
plan limit is the one piece of real enforcement on this page - both need
direct coverage, not just a visual check.
"""

from datetime import timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.bookings.models import Booking
from apps.organizations.models import Membership, Organization
from apps.villas.models import Amenity, Villa, VillaPhoto


@pytest.fixture
def owner_client(client, org, user):
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OWNER)
    client.force_login(user)
    return client


def test_picker_shows_only_this_organizations_villas(owner_client, org, other_org):
    mine = Villa.objects.create(organization=org, name="Mine", slug="mine")
    Villa.objects.create(organization=other_org, name="Not mine", slug="not-mine")

    response = owner_client.get(reverse("villas:list"))
    assert list(response.context["villas"]) == [mine]


def test_inactive_villas_are_hidden_from_the_picker(owner_client, org):
    Villa.objects.create(organization=org, name="Retired", slug="retired", is_active=False)
    response = owner_client.get(reverse("villas:list"))
    assert list(response.context["villas"]) == []


def test_villa_with_a_booking_covering_today_shows_its_checkout_date_as_available_from(owner_client, org, villa):
    today = timezone.localdate()
    check_out = today + timedelta(days=2)
    Booking.objects.create(
        organization=org, villa=villa, check_in=today - timedelta(days=1), check_out=check_out,
    )
    response = owner_client.get(reverse("villas:list"))
    assert response.context["villas"][0].available_from == check_out


def test_villa_with_no_current_booking_is_available_now(owner_client, org, villa):
    response = owner_client.get(reverse("villas:list"))
    assert response.context["villas"][0].available_from is None


@pytest.mark.parametrize(
    "plan,villa_count,expected_limit,expected_can_add",
    [
        (Organization.PlanTier.STARTER, 4, 5, True),
        (Organization.PlanTier.STARTER, 5, 5, False),
        (Organization.PlanTier.GROWTH, 9, 10, True),
        (Organization.PlanTier.PRO, 15, 15, False),
    ],
)
def test_plan_limit_gates_adding_villas(org, plan, villa_count, expected_limit, expected_can_add):
    org.plan = plan
    org.save()
    for i in range(villa_count):
        Villa.objects.create(organization=org, name=f"Villa {i}", slug=f"villa-{i}")

    assert org.villa_limit == expected_limit
    assert org.can_add_villa is expected_can_add


def _test_image(name="photo.png") -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", (100, 80), color=(200, 100, 50)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _valid_payload(**overrides):
    """A complete, valid add-villa submission - mirrors what a real browser
    sends once Django's ModelForm pre-fills the model's own defaults
    (bathrooms, check-in/out times, minimum nights) into the empty form, and
    includes the three things that are mandatory: at least one room type with
    a number, at least one amenity, and a cover photo.
    """
    default_amenity, _created = Amenity.objects.get_or_create(
        name_en="Pool", defaults={"name_id": "Kolam renang"}
    )
    payload = {
        "name": "New Villa",
        "property_type": "villa",
        "address": "Jl. Test No. 1",
        "area": "Canggu",
        "room_type_name": ["Deluxe"],
        "room_type_count": [3],
        "bathrooms": 1,
        "max_guests": 6,
        "check_in_time": "14:00",
        "check_out_time": "11:00",
        "min_nights": 1,
        "amenities": [default_amenity.pk],
        "cover_photo": _test_image(),
    }
    payload.update(overrides)
    return payload


def test_add_villa_form_creates_it_under_the_current_organization(owner_client, org):
    response = owner_client.post(reverse("villas:add"), _valid_payload())
    assert response.status_code == 302
    villa = Villa.objects.get(name="New Villa")
    assert villa.organization == org
    assert villa.slug == "new-villa"


def test_add_villa_auto_generates_a_unique_slug_on_name_collision(owner_client, org):
    Villa.objects.create(organization=org, name="Villa Sunset", slug="villa-sunset")
    owner_client.post(reverse("villas:add"), _valid_payload(name="Villa Sunset"))
    second = Villa.objects.exclude(slug="villa-sunset").get(name="Villa Sunset")
    assert second.slug == "villa-sunset-2"


def test_cannot_add_a_villa_past_the_plan_limit(owner_client, org):
    org.plan = Organization.PlanTier.STARTER
    org.save()
    for i in range(5):
        Villa.objects.create(organization=org, name=f"Villa {i}", slug=f"villa-{i}")

    response = owner_client.post(
        reverse("villas:add"), _valid_payload(name="One Too Many"), follow=True,
    )
    assert not Villa.objects.filter(name="One Too Many").exists()
    assert any("limit" in str(m) for m in response.context["messages"])


def test_direct_post_cannot_bypass_the_disabled_button(owner_client, org):
    """The add-villa card is hidden in the template once the limit is hit,
    but hiding a button is not enforcement - the view must reject the POST
    on its own even if someone submits it directly.
    """
    org.plan = Organization.PlanTier.STARTER
    org.save()
    for i in range(5):
        Villa.objects.create(organization=org, name=f"Villa {i}", slug=f"villa-{i}")

    count_before = Villa.objects.count()
    owner_client.post(
        reverse("villas:add"),
        {
            "name": "Sneaky Villa", "address": "", "area": "", "max_guests": 2,
            "room_type_name": ["Deluxe"], "room_type_count": [1],
        },
    )
    assert Villa.objects.count() == count_before


def test_add_villa_links_selected_amenities(owner_client, org):
    pool = Amenity.objects.create(name_en="Pool", name_id="Kolam renang")
    wifi = Amenity.objects.create(name_en="WiFi", name_id="WiFi")
    Amenity.objects.create(name_en="Sauna", name_id="Sauna")  # left unselected

    owner_client.post(reverse("villas:add"), _valid_payload(amenities=[pool.pk, wifi.pk]))

    villa = Villa.objects.get(name="New Villa")
    assert set(villa.amenities.all()) == {pool, wifi}


def test_amenities_are_required(owner_client, org):
    """No native database constraint can enforce "at least one" on a
    many-to-many, so this rule lives in form validation - and has to be
    proven here, not assumed.
    """
    response = owner_client.post(reverse("villas:add"), _valid_payload(amenities=[]))
    assert response.status_code == 200  # re-rendered with an error, not redirected
    assert not Villa.objects.filter(name="New Villa").exists()
    assert "amenities" in response.context["form"].errors


def test_add_villa_creates_the_room_types_and_their_rooms(owner_client, org):
    owner_client.post(reverse("villas:add"), _valid_payload(
        room_type_name=["Deluxe", "Garden"], room_type_count=[2, 1],
    ))
    villa = Villa.objects.get(name="New Villa")
    assert [c.name for c in villa.room_categories.all()] == ["Deluxe", "Garden"]
    assert [r.name for r in villa.rooms.all()] == ["Deluxe", "Deluxe 2", "Garden"]
    assert villa.bedrooms == 3  # the count follows the rooms, nobody types it


def test_add_villa_needs_at_least_one_room_type(owner_client, org):
    response = owner_client.post(reverse("villas:add"), _valid_payload(
        room_type_name=[""], room_type_count=[""],
    ))
    assert response.status_code == 200
    assert not Villa.objects.filter(name="New Villa").exists()
    assert response.context["form"].non_field_errors()


def test_add_villa_rejects_two_room_types_with_the_same_name(owner_client, org):
    response = owner_client.post(reverse("villas:add"), _valid_payload(
        room_type_name=["Deluxe", "deluxe"], room_type_count=[1, 1],
    ))
    assert response.status_code == 200
    assert not Villa.objects.filter(name="New Villa").exists()


def test_add_villa_rejects_a_room_type_with_no_number(owner_client, org):
    response = owner_client.post(reverse("villas:add"), _valid_payload(
        room_type_name=["Deluxe"], room_type_count=[""],
    ))
    assert response.status_code == 200
    assert not Villa.objects.filter(name="New Villa").exists()


def test_add_villa_keeps_the_room_types_typed_in_when_something_else_fails(owner_client, org):
    """Nobody should have to retype their rooms because a photo was missing."""
    payload = _valid_payload(room_type_name=["Deluxe"], room_type_count=[2])
    del payload["cover_photo"]
    response = owner_client.post(reverse("villas:add"), payload)
    assert response.context["room_type_rows"] == [{"name": "Deluxe", "count": "2"}]


def test_cover_photo_is_converted_to_webp_and_marked_as_cover(owner_client, org):
    owner_client.post(reverse("villas:add"), _valid_payload())
    villa = Villa.objects.get(name="New Villa")
    photo = VillaPhoto.objects.get(villa=villa)
    assert photo.is_cover is True
    assert photo.image.name.endswith(".webp")


def test_cover_photo_is_required(owner_client, org):
    payload = _valid_payload()
    del payload["cover_photo"]
    response = owner_client.post(reverse("villas:add"), payload)
    assert response.status_code == 200
    assert not Villa.objects.filter(name="New Villa").exists()
    assert "cover_photo" in response.context["form"].errors


def test_failed_photo_conversion_rolls_back_the_whole_villa(owner_client, org, monkeypatch):
    """The photo is mandatory, so a conversion failure must not leave a villa
    saved without one - the whole submission fails together.
    """
    from apps.villas import views as villas_views

    def _boom(_uploaded_file):
        raise villas_views.WebPUnavailable("no webp support in this test")

    monkeypatch.setattr(villas_views, "to_webp", _boom)

    response = owner_client.post(reverse("villas:add"), _valid_payload())
    assert response.status_code == 200
    assert not Villa.objects.filter(name="New Villa").exists()
    assert response.context["form"].non_field_errors()


def test_edit_villa_updates_fields_without_a_new_photo(owner_client, org, villa):
    pool = Amenity.objects.create(name_en="Pool", name_id="Kolam renang")
    villa.amenities.add(pool)
    VillaPhoto.objects.create(organization=org, villa=villa, image=_test_image(), is_cover=True)

    payload = _valid_payload(name="Renamed Villa", amenities=[pool.pk])
    del payload["cover_photo"]
    response = owner_client.post(reverse("villas:edit", args=[villa.slug]), payload)

    assert response.status_code == 302
    villa.refresh_from_db()
    assert villa.name == "Renamed Villa"
    assert VillaPhoto.objects.filter(villa=villa).count() == 1


def test_edit_villa_replaces_the_cover_photo_when_a_new_one_is_uploaded(owner_client, org, villa):
    pool = Amenity.objects.create(name_en="Pool", name_id="Kolam renang")
    villa.amenities.add(pool)
    VillaPhoto.objects.create(organization=org, villa=villa, image=_test_image(), is_cover=True)

    payload = _valid_payload(amenities=[pool.pk])
    owner_client.post(reverse("villas:edit", args=[villa.slug]), payload)

    photos = VillaPhoto.objects.filter(villa=villa)
    assert photos.count() == 2
    assert photos.filter(is_cover=True).count() == 1


def test_edit_villa_still_requires_at_least_one_amenity(owner_client, org, villa):
    payload = _valid_payload(amenities=[])
    del payload["cover_photo"]
    response = owner_client.post(reverse("villas:edit", args=[villa.slug]), payload)
    assert response.status_code == 200
    assert "amenities" in response.context["form"].errors


def test_cannot_edit_another_organizations_villa(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Not mine", slug="not-mine")
    response = owner_client.post(reverse("villas:edit", args=[other_villa.slug]), _valid_payload())
    assert response.status_code == 404


def test_delete_villa_shows_a_confirmation_page_first(owner_client, villa):
    response = owner_client.get(reverse("villas:delete", args=[villa.slug]))
    assert response.status_code == 200
    villa.refresh_from_db()
    assert villa.is_active is True


def test_delete_villa_marks_it_inactive_without_erasing_it(owner_client, org, villa):
    response = owner_client.post(reverse("villas:delete", args=[villa.slug]))
    assert response.status_code == 302
    villa.refresh_from_db()
    assert villa.is_active is False
    assert Villa.objects.filter(pk=villa.pk).exists()


def test_deleted_villa_no_longer_appears_on_the_picker(owner_client, villa):
    owner_client.post(reverse("villas:delete", args=[villa.slug]))
    response = owner_client.get(reverse("villas:list"))
    assert villa not in response.context["villas"]


def test_cannot_delete_another_organizations_villa(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Not mine", slug="not-mine")
    response = owner_client.post(reverse("villas:delete", args=[other_villa.slug]))
    assert response.status_code == 404
    other_villa.refresh_from_db()
    assert other_villa.is_active is True

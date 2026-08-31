"""The villa picker, and the two-step form behind "add a villa".

The picker is the first thing anyone sees after logging in, and the plan limit
is the one piece of real enforcement on it - both need direct coverage.

Adding a villa happens in two steps with a real draft row in between, which
brings its own things worth proving: a draft must stay out of sight everywhere
else in the app and must not use up a paid villa slot; going back to step 1
must not lose anything; and a villa must never come out of the flow without
rooms to book, since the calendar draws bookings on room rows only.
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


@pytest.fixture
def pool(db):
    """One of the amenities every operator starts with - seeded by migration
    0011, so it is fetched rather than created. Making a second "Pool" here
    would test against data no real database ever holds.
    """
    return Amenity.objects.get(name_en="Pool", organization=None)


# ---- the picker -----------------------------------------------------------

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


def test_sleeps_adds_up_every_rooms_guests(owner_client, org):
    """The picker's "sleeps N" comes from the room types, not from a number
    typed on the villa - so two rooms for two plus one for four is eight.
    """
    villa = Villa.objects.create(organization=org, name="Compound", slug="compound")
    standard = villa.room_categories.first()
    standard.max_guests = 2
    standard.save()
    from apps.villas.models import create_room_type

    suite = create_room_type(villa, "Suite", how_many=1)
    suite.max_guests = 4
    suite.save()
    from apps.villas.models import set_room_count

    set_room_count(villa, standard, 2)

    assert villa.sleeps == 2 * 2 + 4 * 1


# ---- step 1: about the villa ---------------------------------------------

def _test_image(name="photo.png") -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", (100, 80), color=(200, 100, 50)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _details(**overrides):
    """The three things step 1 actually insists on."""
    payload = {"name": "New Villa", "property_type": "villa", "area": "Canggu"}
    payload.update(overrides)
    return payload


def _finish(villa, **overrides):
    """A complete step-2 submission for a villa with one room type."""
    category = villa.room_categories.first()
    payload = {
        "rooms-TOTAL_FORMS": "1",
        "rooms-INITIAL_FORMS": "1",
        "rooms-0-id": str(category.pk),
        "rooms-0-name": category.name,
        "rooms-0-room_count": "1",
        "rooms-0-max_guests": "2",
        "rooms-0-minimum_nights": "1",
    }
    payload.update(overrides)
    return payload


def test_step_one_saves_a_draft_and_moves_on_to_the_rooms(owner_client, org):
    response = owner_client.post(reverse("villas:add"), _details())

    villa = Villa.objects.get(name="New Villa")
    assert villa.organization == org
    assert villa.slug == "new-villa"
    assert villa.is_draft is True
    assert response.status_code == 302
    assert response.url == reverse("villas:rooms", args=[villa.slug])


def test_step_one_needs_a_name_an_area_and_a_kind_of_place(owner_client):
    response = owner_client.post(reverse("villas:add"), {"name": "", "area": ""})
    assert response.status_code == 200
    assert not Villa.objects.exists()
    assert set(response.context["form"].errors) == {"name", "area", "property_type"}


def test_a_villa_can_be_saved_with_no_photos_at_all(owner_client, org):
    """Photos are optional. A villa with none is a perfectly good villa."""
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")
    owner_client.post(reverse("villas:rooms", args=[villa.slug]), _finish(villa))

    villa.refresh_from_db()
    assert villa.is_draft is False
    assert villa.photos.count() == 0


def test_photos_are_stored_as_webp(owner_client, org):
    owner_client.post(reverse("villas:add"), _details(photos=[_test_image(), _test_image("two.png")]))

    photos = VillaPhoto.objects.filter(villa__name="New Villa")
    assert photos.count() == 2
    assert all(photo.image.name.endswith(".webp") for photo in photos)
    assert photos.filter(is_cover=True).count() == 1


def test_a_photo_that_cannot_become_webp_stops_the_save(owner_client, org, monkeypatch):
    """Never a silent fallback to JPEG - see CLAUDE.md. Nothing is written."""
    from apps.villas import views as villas_views

    def _boom(_uploaded_file):
        raise villas_views.WebPUnavailable("no webp support in this test")

    monkeypatch.setattr(villas_views, "to_webp", _boom)

    response = owner_client.post(reverse("villas:add"), _details(photos=[_test_image()]))
    assert response.status_code == 200
    assert not Villa.objects.filter(name="New Villa").exists()
    assert response.context["form"].non_field_errors()


def test_step_one_auto_generates_a_unique_slug_on_name_collision(owner_client, org):
    Villa.objects.create(organization=org, name="Villa Sunset", slug="villa-sunset")
    owner_client.post(reverse("villas:add"), _details(name="Villa Sunset"))
    second = Villa.objects.exclude(slug="villa-sunset").get(name="Villa Sunset")
    assert second.slug == "villa-sunset-2"


def test_going_back_to_step_one_still_shows_what_was_typed(owner_client, org):
    owner_client.post(reverse("villas:add"), _details(address="Jl. Test No. 1"))
    villa = Villa.objects.get(name="New Villa")

    response = owner_client.get(reverse("villas:add_details", args=[villa.slug]))
    assert response.status_code == 200
    assert response.context["form"].instance == villa
    assert response.context["form"].initial["address"] == "Jl. Test No. 1"


def test_going_back_and_changing_something_does_not_start_a_second_villa(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    owner_client.post(reverse("villas:add_details", args=[villa.slug]), _details(name="Renamed"))

    assert Villa.objects.count() == 1
    villa.refresh_from_db()
    assert villa.name == "Renamed"
    assert villa.slug == "new-villa"  # the web address it was given stays put


def test_check_in_and_out_times_fall_back_when_left_empty(owner_client, org):
    owner_client.post(reverse("villas:add"), _details(check_in_time="", check_out_time=""))
    villa = Villa.objects.get(name="New Villa")
    assert villa.check_in_time.hour == 14
    assert villa.check_out_time.hour == 11


def test_a_link_that_is_not_a_link_is_refused(owner_client, org):
    response = owner_client.post(reverse("villas:add"), _details(google_maps_url="somewhere in canggu"))
    assert response.status_code == 200
    assert "google_maps_url" in response.context["form"].errors


# ---- drafts ---------------------------------------------------------------

def test_a_draft_is_hidden_from_the_picker_but_offered_to_be_finished(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    response = owner_client.get(reverse("villas:list"))
    assert list(response.context["villas"]) == []
    assert list(response.context["drafts"]) == [villa]


def test_a_draft_does_not_use_up_a_villa_on_the_plan(owner_client, org):
    org.plan = Organization.PlanTier.STARTER
    org.save()
    for i in range(4):
        Villa.objects.create(organization=org, name=f"Villa {i}", slug=f"villa-{i}")

    owner_client.post(reverse("villas:add"), _details())
    org.refresh_from_db()

    assert Villa.objects.filter(organization=org).count() == 5
    assert org.can_add_villa is True  # the draft isn't finished, so it doesn't count


def test_a_draft_is_kept_off_the_booking_calendar(owner_client, org, villa):
    """A half-added villa has nothing to show yet, so it must not appear as an
    empty row on the calendar next to the real ones.
    """
    owner_client.post(reverse("villas:add"), _details(name="Half Done"))

    body = owner_client.get(reverse("bookings:calendar")).content.decode()
    assert villa.name in body
    assert "Half Done" not in body


def test_finishing_a_draft_makes_it_a_real_villa(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    response = owner_client.post(reverse("villas:rooms", args=[villa.slug]), _finish(villa))

    assert response.status_code == 302
    assert response.url == reverse("villas:list")
    villa.refresh_from_db()
    assert villa.is_draft is False
    assert list(owner_client.get(reverse("villas:list")).context["villas"]) == [villa]


def test_cannot_start_a_new_villa_past_the_plan_limit(owner_client, org):
    org.plan = Organization.PlanTier.STARTER
    org.save()
    for i in range(5):
        Villa.objects.create(organization=org, name=f"Villa {i}", slug=f"villa-{i}")

    response = owner_client.post(reverse("villas:add"), _details(name="One Too Many"), follow=True)
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
    owner_client.post(reverse("villas:add"), _details(name="Sneaky Villa"))
    assert Villa.objects.count() == count_before


# ---- step 2: the rooms ----------------------------------------------------

def test_a_new_villa_starts_step_two_with_one_room_type_ready(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    assert [c.name for c in villa.room_categories.all()] == ["Standard"]
    response = owner_client.get(reverse("villas:rooms", args=[villa.slug]))
    assert response.status_code == 200
    assert len(response.context["formset"].forms) == 1


def test_step_two_saves_each_room_types_details(owner_client, org, pool):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    owner_client.post(reverse("villas:rooms", args=[villa.slug]), _finish(
        villa,
        **{
            "rooms-0-name": "Garden",
            "rooms-0-room_count": "3",
            "rooms-0-max_guests": "4",
            "rooms-0-size_sqm": "35",
            "rooms-0-minimum_nights": "2",
            "rooms-0-nightly_rate": "1500000",
            "rooms-0-monthly_rate": "30000000",
            "rooms-0-amenities": [str(pool.pk)],
        },
    ))

    category = villa.room_categories.get()
    assert category.name == "Garden"
    assert category.max_guests == 4
    assert category.size_sqm == 35
    assert category.minimum_nights == 2
    assert category.nightly_rate == 1_500_000
    assert category.monthly_rate == 30_000_000
    assert list(category.amenities.all()) == [pool]
    assert [r.name for r in villa.rooms.all()] == ["Garden", "Garden 2", "Garden 3"]


@pytest.mark.parametrize("typed", ["1.500.000", "1,500,000", "1 500 000", "1500000"])
def test_a_price_can_be_typed_with_or_without_separators(owner_client, org, typed):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-nightly_rate": typed}),
    )
    assert villa.room_categories.get().nightly_rate == 1_500_000


def test_a_price_that_is_not_a_number_is_refused_in_plain_words(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    response = owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-nightly_rate": "about a million"}),
    )
    assert response.status_code == 200
    errors = response.context["formset"].forms[0].errors["nightly_rate"]
    assert "1.500.000" in errors[0]


def test_a_room_type_needs_a_name(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    response = owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-name": ""}),
    )
    assert response.status_code == 200
    villa.refresh_from_db()
    assert villa.is_draft is True  # not finished, so nothing was lost either
    assert "name" in response.context["formset"].forms[0].errors


def test_two_room_types_cannot_share_a_name(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")
    owner_client.post(
        reverse("villas:add_room_category", args=[villa.slug]),
        {"rooms-TOTAL_FORMS": "0", "rooms-INITIAL_FORMS": "0"},
    )
    first, second = list(villa.room_categories.order_by("sort_order"))

    response = owner_client.post(reverse("villas:rooms", args=[villa.slug]), {
        "rooms-TOTAL_FORMS": "2", "rooms-INITIAL_FORMS": "2",
        "rooms-0-id": str(first.pk), "rooms-0-name": "Garden",
        "rooms-0-room_count": "1", "rooms-0-max_guests": "2", "rooms-0-minimum_nights": "1",
        "rooms-1-id": str(second.pk), "rooms-1-name": "garden",
        "rooms-1-room_count": "1", "rooms-1-max_guests": "2", "rooms-1-minimum_nights": "1",
    })

    assert response.status_code == 200
    assert "different name" in str(response.context["formset"].forms[1].errors["name"])


def test_lowering_the_number_of_rooms_removes_them(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")
    owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-room_count": "4"}),
    )
    assert villa.rooms.count() == 4

    owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-room_count": "2"}),
    )
    assert villa.rooms.count() == 2


def test_lowering_the_number_takes_an_empty_room_before_a_booked_one(owner_client, org, guest):
    """Booking.room is PROTECT on purpose - lowering a number must never take
    a real booking off the calendar. An empty room goes in a booked one's place.
    """
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")
    owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-room_count": "3"}),
    )

    today = timezone.localdate()
    booked = villa.rooms.order_by("id").last()
    Booking.objects.create(
        organization=org, villa=villa, room=booked, guest=guest,
        check_in=today, check_out=today + timedelta(days=2),
    )

    owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-room_count": "2"}),
    )

    assert villa.rooms.count() == 2
    assert booked in villa.rooms.all()  # the booked one survived, an empty one went


def test_a_number_that_cannot_be_reached_says_so_instead_of_pretending(owner_client, org, guest):
    """When too many rooms are booked to get down to the number asked for,
    fewer are removed - and the screen has to say so rather than showing a
    number that isn't true.
    """
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")
    owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-room_count": "3"}),
    )

    today = timezone.localdate()
    for room in villa.rooms.order_by("id")[1:]:
        Booking.objects.create(
            organization=org, villa=villa, room=room, guest=guest,
            check_in=today, check_out=today + timedelta(days=2),
        )

    response = owner_client.post(
        reverse("villas:rooms", args=[villa.slug]),
        _finish(villa, **{"rooms-0-room_count": "1"}),
        follow=True,
    )
    assert villa.rooms.count() == 2  # not 1 - two of them are booked
    assert any("bookings" in str(m) for m in response.context["messages"])


def test_cannot_touch_another_organizations_rooms(owner_client, other_org):
    other = Villa.objects.create(organization=other_org, name="Not mine", slug="not-mine")
    response = owner_client.post(reverse("villas:rooms", args=[other.slug]), _finish(other))
    assert response.status_code == 404


# ---- adding and removing room blocks -------------------------------------

def _htmx(owner_client, url, payload):
    return owner_client.post(url, payload, headers={"HX-Request": "true"})


def test_adding_a_block_creates_a_real_room_type(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    response = _htmx(owner_client, reverse("villas:add_room_category", args=[villa.slug]), {
        "rooms-TOTAL_FORMS": "1", "rooms-INITIAL_FORMS": "1",
        "rooms-0-id": str(villa.room_categories.first().pk),
        "rooms-0-name": "Garden", "rooms-0-room_count": "1",
        "rooms-0-max_guests": "2", "rooms-0-minimum_nights": "1",
    })

    assert response.status_code == 200
    assert villa.room_categories.count() == 2
    body = response.content.decode()
    assert "rooms-1-name" in body           # the new block came back
    assert 'value="Garden"' in body         # and the first one kept what was typed


def test_a_second_block_starts_with_the_first_ones_amenities_ticked(owner_client, org, pool):
    """Most kinds of room in one villa come with the same things. Re-ticking
    the same boxes is exactly the busywork this product exists to remove.
    """
    wifi = Amenity.objects.get(name_en="WiFi", organization=None)
    Amenity.objects.create(name_en="Sauna", name_id="Sauna")  # deliberately not ticked

    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")

    _htmx(owner_client, reverse("villas:add_room_category", args=[villa.slug]), {
        "rooms-TOTAL_FORMS": "1", "rooms-INITIAL_FORMS": "1",
        "rooms-0-id": str(villa.room_categories.first().pk),
        "rooms-0-name": "Garden", "rooms-0-room_count": "1",
        "rooms-0-max_guests": "2", "rooms-0-minimum_nights": "1",
        "rooms-0-amenities": [str(pool.pk), str(wifi.pk)],
    })

    second = villa.room_categories.order_by("sort_order").last()
    assert set(second.amenities.all()) == {pool, wifi}


def test_removing_a_block_keeps_what_was_typed_in_the_others(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")
    _htmx(owner_client, reverse("villas:add_room_category", args=[villa.slug]),
          {"rooms-TOTAL_FORMS": "0", "rooms-INITIAL_FORMS": "0"})
    first, second = list(villa.room_categories.order_by("sort_order"))

    response = _htmx(
        owner_client, reverse("villas:remove_room_category", args=[villa.slug, first.pk]), {
            "rooms-TOTAL_FORMS": "2", "rooms-INITIAL_FORMS": "2",
            "rooms-0-id": str(first.pk), "rooms-0-name": "Going",
            "rooms-0-room_count": "1", "rooms-0-max_guests": "2", "rooms-0-minimum_nights": "1",
            "rooms-1-id": str(second.pk), "rooms-1-name": "Staying",
            "rooms-1-room_count": "1", "rooms-1-max_guests": "6", "rooms-1-minimum_nights": "1",
        },
    )

    assert response.status_code == 200
    assert villa.room_categories.count() == 1
    body = response.content.decode()
    # The survivor moved up to slot 0 and brought its typed values with it.
    assert 'name="rooms-0-name" value="Staying"' in body.replace("  ", " ")
    assert "rooms-1-name" not in body
    assert 'value="6"' in body


def test_the_last_room_type_cannot_be_removed(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")
    only = villa.room_categories.get()

    response = _htmx(
        owner_client, reverse("villas:remove_room_category", args=[villa.slug, only.pk]),
        _finish(villa),
    )

    assert response.status_code == 200
    assert villa.room_categories.count() == 1
    assert "at least one room type" in response.content.decode()


def test_a_removed_room_types_rooms_move_rather_than_disappear(owner_client, org):
    owner_client.post(reverse("villas:add"), _details())
    villa = Villa.objects.get(name="New Villa")
    _htmx(owner_client, reverse("villas:add_room_category", args=[villa.slug]),
          {"rooms-TOTAL_FORMS": "0", "rooms-INITIAL_FORMS": "0"})
    first, second = list(villa.room_categories.order_by("sort_order"))
    rooms_before = villa.rooms.count()

    _htmx(owner_client, reverse("villas:remove_room_category", args=[villa.slug, first.pk]), {
        "rooms-TOTAL_FORMS": "2", "rooms-INITIAL_FORMS": "2",
        "rooms-0-id": str(first.pk), "rooms-0-name": first.name,
        "rooms-0-room_count": "1", "rooms-0-max_guests": "2", "rooms-0-minimum_nights": "1",
        "rooms-1-id": str(second.pk), "rooms-1-name": second.name,
        "rooms-1-room_count": "1", "rooms-1-max_guests": "2", "rooms-1-minimum_nights": "1",
    })

    assert villa.rooms.count() == rooms_before
    assert set(villa.rooms.values_list("category_id", flat=True)) == {second.pk}


def test_cannot_add_a_room_type_to_another_organizations_villa(owner_client, other_org):
    other = Villa.objects.create(organization=other_org, name="Not mine", slug="not-mine")
    response = owner_client.post(
        reverse("villas:add_room_category", args=[other.slug]),
        {"rooms-TOTAL_FORMS": "0", "rooms-INITIAL_FORMS": "0"},
    )
    assert response.status_code == 404


# ---- amenities ------------------------------------------------------------

def test_an_operator_can_add_their_own_amenity_and_reuse_it(owner_client, org):
    response = _htmx(owner_client, reverse("villas:add_amenity"), {
        "new_amenity_1": "Yoga deck", "field_name": "rooms-0-amenities", "category_pk": "1",
    })

    assert response.status_code == 200
    amenity = Amenity.objects.get(name_en="Yoga deck")
    assert amenity.organization == org
    assert amenity.name_id == "Yoga deck"  # their own wording, both languages
    assert amenity in Amenity.available_to(org)


def test_one_operators_own_amenity_is_never_offered_to_another(owner_client, org, other_org):
    _htmx(owner_client, reverse("villas:add_amenity"), {"new_amenity_1": "Yoga deck", "category_pk": "1"})
    mine = Amenity.objects.get(name_en="Yoga deck")

    assert mine in Amenity.available_to(org)
    assert mine not in Amenity.available_to(other_org)


def test_the_shared_amenities_are_offered_to_everyone(org, other_org, pool):
    assert pool.organization is None
    assert pool in Amenity.available_to(org)
    assert pool in Amenity.available_to(other_org)


def test_adding_an_amenity_that_already_exists_says_so(owner_client, org, pool):
    response = _htmx(owner_client, reverse("villas:add_amenity"), {"new_amenity_1": "pool", "category_pk": "1"})
    assert response.status_code == 200
    assert "already on the list" in response.content.decode()
    assert Amenity.objects.filter(name_en__iexact="pool").count() == 1


# ---- editing and removing -------------------------------------------------

def test_edit_page_shows_the_villa(owner_client, villa):
    response = owner_client.get(reverse("villas:edit", args=[villa.slug]))
    assert response.status_code == 200
    assert response.context["form"].instance == villa


def test_the_rooms_step_of_editing_shows_the_room_blocks(owner_client, villa):
    response = owner_client.get(reverse("villas:rooms", args=[villa.slug]))
    assert response.status_code == 200
    assert len(response.context["formset"].forms) == villa.room_categories.count()


def test_edit_page_saves_the_villas_details(owner_client, villa):
    response = owner_client.post(
        reverse("villas:edit", args=[villa.slug]), _details(name="Renamed Villa"),
    )
    assert response.status_code == 302
    villa.refresh_from_db()
    assert villa.name == "Renamed Villa"
    assert villa.is_draft is False


def test_editing_the_rooms_of_a_finished_villa_comes_back_to_the_edit_page(owner_client, villa):
    response = owner_client.post(reverse("villas:rooms", args=[villa.slug]), _finish(villa))
    assert response.status_code == 302
    assert response.url == reverse("villas:edit", args=[villa.slug])


def test_adding_a_photo_to_the_edit_page_keeps_the_ones_already_there(owner_client, org, villa):
    VillaPhoto.objects.create(organization=org, villa=villa, image=_test_image(), is_cover=True)
    owner_client.post(
        reverse("villas:edit", args=[villa.slug]), _details(photos=[_test_image("second.png")]),
    )
    assert villa.photos.count() == 2
    assert villa.photos.filter(is_cover=True).count() == 1


def test_a_photo_can_be_removed_on_its_own(owner_client, org, villa):
    photo = VillaPhoto.objects.create(organization=org, villa=villa, image=_test_image())
    response = _htmx(
        owner_client, reverse("villas:remove_villa_photo", args=[villa.slug, photo.pk]), {},
    )
    assert response.status_code == 200
    assert villa.photos.count() == 0


def test_cannot_edit_another_organizations_villa(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Not mine", slug="not-mine")
    response = owner_client.post(reverse("villas:edit", args=[other_villa.slug]), _details())
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

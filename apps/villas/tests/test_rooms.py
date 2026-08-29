"""Rooms are made a type at a time: the operator names the type ("Deluxe")
and says how many there are, and that many rooms appear - "Deluxe", "Deluxe 2",
"Deluxe 3" - each renameable afterwards.

So the tests worth having are: the names come out in that series and never
collide; the number can be raised and lowered from the villa's rooms panel;
a room that still has bookings survives a lowered number (Booking.room is
PROTECT, on purpose - see apps/bookings/models.py - so a removal never leaves
a booking pointing at nothing and silently vanishing from the calendar); a
villa's last room can't be removed; and none of it can be done to another
organization's villa.
"""

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.bookings.models import Booking
from apps.guests.services import find_or_create_guest
from apps.organizations.models import Membership
from apps.villas.models import (
    Room,
    Villa,
    add_rooms,
    create_room_type,
    next_room_names,
    set_room_count,
)


@pytest.fixture
def owner_client(client, org, user):
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OWNER)
    client.force_login(user)
    return client


# ---- how rooms are named --------------------------------------------------

def test_every_new_villa_starts_with_one_room_type_and_one_room(org):
    villa = Villa.objects.create(organization=org, name="Fresh", slug="fresh")
    assert [c.name for c in villa.room_categories.all()] == ["Standard"]
    assert [r.name for r in villa.rooms.all()] == ["Standard"]


def test_a_villa_created_with_bedrooms_starts_with_that_many_rooms(org):
    """Villas made outside the add form - the admin, the seed command - have
    no room types typed in, so their bedroom number decides how many rooms
    they start with.
    """
    villa = Villa.objects.create(organization=org, name="Big", slug="big", bedrooms=4)
    assert [r.name for r in villa.rooms.all()] == [
        "Standard", "Standard 2", "Standard 3", "Standard 4",
    ]


def test_a_room_type_names_its_rooms_after_itself(org, villa):
    create_room_type(villa, "Deluxe", how_many=3)
    deluxe = villa.room_categories.get(name="Deluxe")
    assert [r.name for r in deluxe.rooms.order_by("id")] == ["Deluxe", "Deluxe 2", "Deluxe 3"]


def test_more_rooms_follow_the_first_rooms_name_after_it_is_renamed(org, villa):
    """"The name of the rooms follows the name of the first room" - rename it
    to Kenanga and the next ones carry on from there, not from the type.
    """
    deluxe = create_room_type(villa, "Deluxe", how_many=3)
    first = deluxe.rooms.order_by("id").first()
    first.name = "Kenanga"
    first.save(update_fields=["name"])

    add_rooms(villa, deluxe, 2)
    assert [r.name for r in deluxe.rooms.order_by("id")] == [
        "Kenanga", "Deluxe 2", "Deluxe 3", "Kenanga 4", "Kenanga 5",
    ]


def test_new_room_names_skip_ones_already_used_in_the_villa(org, villa):
    deluxe = create_room_type(villa, "Deluxe", how_many=1)
    Room.objects.create(organization=org, villa=villa, name="Deluxe 2", category=deluxe)
    assert next_room_names(villa, deluxe, 2) == ["Deluxe 3", "Deluxe 4"]


def test_numbering_carries_on_from_a_room_that_already_ends_in_a_number(org):
    """Older villas have rooms called "Standard 1", "Standard 2" - adding more
    continues that series instead of starting a second one.
    """
    villa = Villa.objects.create(organization=org, name="Old", slug="old")
    standard = villa.room_categories.get(name="Standard")
    villa.rooms.update(name="Standard 1")
    assert next_room_names(villa, standard, 2) == ["Standard 2", "Standard 3"]


def test_adding_rooms_keeps_the_villas_room_count_right(org, villa):
    create_room_type(villa, "Deluxe", how_many=3)
    villa.refresh_from_db()
    assert villa.bedrooms == villa.rooms.count() == 4  # its starter room plus three


# ---- changing how many rooms a type has -----------------------------------

def test_raising_the_number_adds_rooms(org, villa):
    deluxe = create_room_type(villa, "Deluxe", how_many=1)
    added, removed = set_room_count(villa, deluxe, 3)
    assert (added, removed) == (2, 0)
    assert deluxe.rooms.count() == 3


def test_lowering_the_number_removes_the_newest_rooms(org, villa):
    deluxe = create_room_type(villa, "Deluxe", how_many=3)
    added, removed = set_room_count(villa, deluxe, 1)
    assert (added, removed) == (0, 2)
    assert [r.name for r in deluxe.rooms.all()] == ["Deluxe"]


def test_lowering_the_number_skips_a_room_that_still_has_bookings(org, villa):
    """The newest room goes first, unless it has bookings on it - then an
    emptier one goes instead and the booked room stays on the calendar.
    """
    deluxe = create_room_type(villa, "Deluxe", how_many=2)
    booked = deluxe.rooms.order_by("id").last()
    guest = find_or_create_guest(org, full_name="A Guest")
    Booking.objects.create(
        organization=org, villa=villa, room=booked, guest=guest,
        check_in="2026-09-01", check_out="2026-09-05",
    )

    added, removed = set_room_count(villa, deluxe, 1)
    assert (added, removed) == (0, 1)
    assert [r.pk for r in deluxe.rooms.all()] == [booked.pk]


def test_lowering_the_number_stops_short_when_every_room_is_booked(org, villa):
    deluxe = create_room_type(villa, "Deluxe", how_many=2)
    guest = find_or_create_guest(org, full_name="A Guest")
    for room in deluxe.rooms.all():
        Booking.objects.create(
            organization=org, villa=villa, room=room, guest=guest,
            check_in="2026-09-01", check_out="2026-09-05",
        )

    added, removed = set_room_count(villa, deluxe, 1)
    assert (added, removed) == (0, 0)
    assert deluxe.rooms.count() == 2


def test_lowering_the_number_never_removes_a_villas_last_room(org):
    villa = Villa.objects.create(organization=org, name="Solo", slug="solo")
    standard = villa.room_categories.get(name="Standard")
    set_room_count(villa, standard, 1)  # it already has exactly one
    assert villa.rooms.count() == 1


# ---- the villa's rooms panel ----------------------------------------------

def test_the_add_page_offers_a_room_type_row(owner_client):
    response = owner_client.get(reverse("villas:add"))
    assert response.status_code == 200
    assert response.context["room_type_rows"] == [{"name": "", "count": 1}]
    assert b'name="room_type_name"' in response.content


def test_the_edit_page_lists_each_room_type_with_its_rooms(owner_client, villa):
    create_room_type(villa, "Deluxe", how_many=2)
    response = owner_client.get(reverse("villas:edit", args=[villa.slug]))
    assert response.status_code == 200
    assert [g["category"].name for g in response.context["room_groups"]] == ["Standard", "Deluxe"]
    assert [r.name for r in response.context["room_groups"][1]["rooms"]] == ["Deluxe", "Deluxe 2"]


def test_add_room_type_creates_it_with_that_many_rooms(owner_client, villa):
    response = owner_client.post(
        reverse("villas:add_room_category", args=[villa.slug]),
        {"name": "Garden view", "count": 3},
    )
    assert response.status_code == 302
    garden = villa.room_categories.get(name="Garden view")
    assert [r.name for r in garden.rooms.order_by("id")] == [
        "Garden view", "Garden view 2", "Garden view 3",
    ]


def test_add_room_type_rejects_a_duplicate_name(owner_client, villa):
    before = villa.room_categories.count()
    owner_client.post(
        reverse("villas:add_room_category", args=[villa.slug]),
        {"name": "standard", "count": 1}, follow=True,
    )
    assert villa.room_categories.count() == before


def test_add_room_type_rejects_a_missing_number(owner_client, villa):
    owner_client.post(
        reverse("villas:add_room_category", args=[villa.slug]),
        {"name": "Garden view", "count": ""}, follow=True,
    )
    assert not villa.room_categories.filter(name="Garden view").exists()


def test_cannot_add_a_room_type_to_another_organizations_villa(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    response = owner_client.post(
        reverse("villas:add_room_category", args=[other_villa.slug]),
        {"name": "Sneaky", "count": 1},
    )
    assert response.status_code == 404
    assert not other_villa.room_categories.filter(name="Sneaky").exists()


def test_saving_a_room_type_renames_it_and_its_rooms_and_changes_the_number(owner_client, villa):
    deluxe = create_room_type(villa, "Deluxe", how_many=2)
    first, second = deluxe.rooms.order_by("id")

    response = owner_client.post(
        reverse("villas:save_room_category", args=[villa.slug, deluxe.pk]),
        {
            "name": "Kenanga",
            "count": 3,
            f"room_name_{first.pk}": "Kenanga suite",
            f"room_name_{second.pk}": "Deluxe 2",
        },
    )
    assert response.status_code == 302
    deluxe.refresh_from_db()
    assert deluxe.name == "Kenanga"
    # Renames land before the new room is named, so it follows the new name.
    assert [r.name for r in deluxe.rooms.order_by("id")] == [
        "Kenanga suite", "Deluxe 2", "Kenanga suite 3",
    ]


def test_saving_a_room_type_with_a_lower_number_removes_rooms(owner_client, villa):
    deluxe = create_room_type(villa, "Deluxe", how_many=3)
    owner_client.post(
        reverse("villas:save_room_category", args=[villa.slug, deluxe.pk]),
        {"name": "Deluxe", "count": 1},
    )
    assert deluxe.rooms.count() == 1


def test_a_room_type_can_be_emptied_without_being_removed(owner_client, villa):
    """Older villas carry room types with nothing filed under them, and an
    operator can empty one on purpose - the panel has to accept zero.
    """
    deluxe = create_room_type(villa, "Deluxe", how_many=2)
    response = owner_client.post(
        reverse("villas:save_room_category", args=[villa.slug, deluxe.pk]),
        {"name": "Deluxe", "count": 0}, follow=True,
    )
    assert response.status_code == 200
    assert deluxe.rooms.count() == 0
    assert villa.room_categories.filter(pk=deluxe.pk).exists()


def test_saving_a_room_type_rejects_a_number_that_is_not_one(owner_client, villa):
    deluxe = create_room_type(villa, "Deluxe", how_many=2)
    owner_client.post(
        reverse("villas:save_room_category", args=[villa.slug, deluxe.pk]),
        {"name": "Deluxe", "count": "lots"}, follow=True,
    )
    assert deluxe.rooms.count() == 2


def test_saving_a_lower_number_says_so_when_a_booked_room_is_kept(owner_client, org, villa):
    """Honest rather than silent: the number on screen can't quietly pretend
    a room with bookings on it was removed.
    """
    deluxe = create_room_type(villa, "Deluxe", how_many=2)
    guest = find_or_create_guest(org, full_name="A Guest")
    for room in deluxe.rooms.all():
        Booking.objects.create(
            organization=org, villa=villa, room=room, guest=guest,
            check_in="2026-09-01", check_out="2026-09-05",
        )

    response = owner_client.post(
        reverse("villas:save_room_category", args=[villa.slug, deluxe.pk]),
        {"name": "Deluxe", "count": 1}, follow=True,
    )
    assert deluxe.rooms.count() == 2
    assert any("bookings" in str(m) for m in response.context["messages"])


def test_saving_a_room_type_rejects_a_name_another_type_already_has(owner_client, villa):
    deluxe = create_room_type(villa, "Deluxe", how_many=1)
    owner_client.post(
        reverse("villas:save_room_category", args=[villa.slug, deluxe.pk]),
        {"name": "Standard", "count": 1}, follow=True,
    )
    deluxe.refresh_from_db()
    assert deluxe.name == "Deluxe"


def test_cannot_save_a_room_type_on_another_organizations_villa(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    category = other_villa.room_categories.first()
    response = owner_client.post(
        reverse("villas:save_room_category", args=[other_villa.slug, category.pk]),
        {"name": "Hijacked", "count": 1},
    )
    assert response.status_code == 404
    category.refresh_from_db()
    assert category.name == "Standard"


def test_removing_a_room_type_moves_its_rooms_to_another_one(owner_client, villa):
    """Tidying up a label must never delete real rooms - they change type."""
    deluxe = create_room_type(villa, "Deluxe", how_many=2)
    response = owner_client.post(
        reverse("villas:remove_room_category", args=[villa.slug, deluxe.pk]), follow=True
    )
    assert response.status_code == 200
    assert not villa.room_categories.filter(name="Deluxe").exists()
    assert villa.rooms.count() == 3
    assert set(villa.rooms.values_list("category__name", flat=True)) == {"Standard"}


def test_cannot_remove_the_only_room_type_while_rooms_use_it(owner_client, villa):
    standard = villa.room_categories.get(name="Standard")
    response = owner_client.post(
        reverse("villas:remove_room_category", args=[villa.slug, standard.pk]), follow=True
    )
    assert villa.room_categories.filter(pk=standard.pk).exists()
    assert any("another room type" in str(m) for m in response.context["messages"])


def test_cannot_remove_a_room_type_from_another_organizations_villa(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    category = other_villa.room_categories.first()
    response = owner_client.post(
        reverse("villas:remove_room_category", args=[other_villa.slug, category.pk])
    )
    assert response.status_code == 404
    assert other_villa.room_categories.filter(pk=category.pk).exists()


def test_every_new_villa_gets_its_own_room_types(org):
    a = Villa.objects.create(organization=org, name="A", slug="a")
    b = Villa.objects.create(organization=org, name="B", slug="b")
    # Separate rows per villa, so renaming one villa's type leaves the other's alone.
    assert not set(a.room_categories.values_list("pk", flat=True)) & set(
        b.room_categories.values_list("pk", flat=True)
    )


def test_renaming_one_villas_room_type_leaves_other_villas_alone(org):
    a = Villa.objects.create(organization=org, name="A", slug="a")
    b = Villa.objects.create(organization=org, name="B", slug="b")
    standard = a.room_categories.get(name="Standard")
    standard.name = "Ocean view"
    standard.save()
    assert b.room_categories.filter(name="Standard").exists()


def test_a_room_cannot_use_another_villas_room_type(org, villa):
    other = Villa.objects.create(organization=org, name="Other", slug="other")
    room = Room(
        organization=org, villa=villa, name="X",
        category=other.room_categories.first(),
    )
    with pytest.raises(ValidationError):
        room.full_clean()


# ---- removing single rooms ------------------------------------------------

def test_remove_room_deletes_it_when_the_villa_has_another_room(owner_client, villa):
    # The villa's own starter room already exists - this is its second room,
    # so removing it is safe.
    room = Room.objects.create(organization=villa.organization, villa=villa, name="Melati 1")
    response = owner_client.post(reverse("villas:remove_room", args=[villa.slug, room.pk]))
    assert response.status_code == 302
    assert not Room.objects.filter(pk=room.pk).exists()


def test_cannot_remove_a_villas_last_room(owner_client, villa):
    room = villa.rooms.get()  # the one created with the villa
    response = owner_client.post(reverse("villas:remove_room", args=[villa.slug, room.pk]), follow=True)
    assert response.status_code == 200
    assert Room.objects.filter(pk=room.pk).exists()


def test_cannot_remove_a_room_that_still_has_bookings(owner_client, org, villa):
    room = Room.objects.create(organization=org, villa=villa, name="Melati 1")
    guest = find_or_create_guest(org, full_name="A Guest")
    booking = Booking.objects.create(
        organization=org, villa=villa, room=room, guest=guest,
        check_in="2026-09-01", check_out="2026-09-05",
    )
    response = owner_client.post(reverse("villas:remove_room", args=[villa.slug, room.pk]), follow=True)
    assert response.status_code == 200
    assert Room.objects.filter(pk=room.pk).exists()
    booking.refresh_from_db()
    assert booking.room_id == room.id  # untouched, not silently detached


def test_cannot_remove_a_room_from_another_organizations_villa(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    room = Room.objects.create(organization=other_org, villa=other_villa, name="Room 1")
    response = owner_client.post(reverse("villas:remove_room", args=[other_villa.slug, room.pk]))
    assert response.status_code == 404
    assert Room.objects.filter(pk=room.pk).exists()


def test_removing_a_room_lowers_the_villas_room_count(org, villa):
    room = Room.objects.create(organization=org, villa=villa, name="Extra")
    room.delete()
    villa.refresh_from_db()
    assert villa.bedrooms == 1


# ---- inline renaming and the calendar's one-click add ---------------------

def test_rename_villa_updates_the_name(owner_client, villa):
    response = owner_client.post(reverse("villas:rename", args=[villa.slug]), {"name": "New Name"})
    assert response.status_code == 204
    villa.refresh_from_db()
    assert villa.name == "New Name"


def test_rename_villa_ignores_a_blank_name(owner_client, villa):
    original = villa.name
    owner_client.post(reverse("villas:rename", args=[villa.slug]), {"name": ""})
    villa.refresh_from_db()
    assert villa.name == original


def test_cannot_rename_another_organizations_villa(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    response = owner_client.post(reverse("villas:rename", args=[other_villa.slug]), {"name": "Hijacked"})
    assert response.status_code == 404
    other_villa.refresh_from_db()
    assert other_villa.name == "Other"


def test_rename_room_updates_the_name(owner_client, villa):
    room = villa.rooms.get()
    response = owner_client.post(reverse("villas:rename_room", args=[villa.slug, room.pk]), {"name": "Suite A"})
    assert response.status_code == 204
    room.refresh_from_db()
    assert room.name == "Suite A"


def test_quick_add_room_follows_the_villas_first_room_type(owner_client, villa):
    response = owner_client.post(reverse("villas:quick_add_room", args=[villa.slug]))
    assert response.status_code == 302
    assert villa.rooms.count() == 2  # the starter "Standard" plus this one
    new_room = villa.rooms.exclude(name="Standard").get()
    assert new_room.name == "Standard 2"
    assert new_room.category.name == "Standard"


def test_quick_add_room_redirects_to_a_safe_next_url(owner_client, villa):
    response = owner_client.post(
        reverse("villas:quick_add_room", args=[villa.slug]), {"next": "/bookings/calendar/?days=30"}
    )
    assert response.url == "/bookings/calendar/?days=30"


def test_quick_add_room_ignores_an_unsafe_next_url(owner_client, villa):
    response = owner_client.post(
        reverse("villas:quick_add_room", args=[villa.slug]), {"next": "https://evil.example/"}
    )
    assert response.url == reverse("villas:edit", args=[villa.slug])

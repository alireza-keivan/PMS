"""Villas, their room types, the rooms themselves, and their photos.

How rooms come into being: the operator names a room type ("Deluxe") and says
how many of them the villa has. That makes the rooms, named after the type -
"Deluxe", "Deluxe 2", "Deluxe 3" - and every one of them can be renamed later.
There is no separate "number of bedrooms" to type in: `Villa.bedrooms` is now
just a cached count of the rooms that exist, kept in step by the signals at
the bottom of this module.
"""

import re
from datetime import time

from django.db import models
from django.db.models import ProtectedError
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel

# A villa created outside the add form - Django admin, the seed command, a
# shell script - still needs somewhere to put its rooms, so it starts with
# this one type. Deliberately not translated: a room type, like a room name,
# is stored operator data they rename at will, so it must not change meaning
# when the page language changes.
DEFAULT_ROOM_TYPE = "Standard"

# A sanity ceiling on "how many rooms", not a plan limit - it stops a typo
# like 300 from filling a villa with hundreds of rooms nobody asked for.
MAX_ROOMS_PER_TYPE = 60


class Villa(TenantOwnedModel):
    class PropertyType(models.TextChoices):
        VILLA = "villa", _("Villa")
        GUESTHOUSE = "guesthouse", _("Guesthouse")
        APARTMENT = "apartment", _("Apartment")
        HOUSE = "house", _("House")

    # ---- identity -----------------------------------------------------
    name = models.CharField(max_length=160)
    slug = models.SlugField(help_text=_("Used in the villa's public web address."))
    property_type = models.CharField(
        max_length=20, choices=PropertyType.choices, default=PropertyType.VILLA
    )

    # ---- location -------------------------------------------------------
    area = models.CharField(
        max_length=80, blank=True, help_text=_("Canggu, Ubud, Uluwatu, Seminyak.")
    )
    address = models.TextField(blank=True)
    google_maps_url = models.URLField(
        blank=True, help_text=_("Paste a Google Maps link so staff and guests can find it.")
    )

    # ---- capacity ---------------------------------------------------------
    # Not typed in on the villa form any more - it counts the rooms the villa
    # actually has (see the signals at the bottom of this module). Set on a
    # villa created outside that form, it decides how many rooms it starts
    # with; after that it only ever follows the Room table.
    bedrooms = models.PositiveSmallIntegerField(default=1)
    bathrooms = models.PositiveSmallIntegerField(default=1)
    max_guests = models.PositiveSmallIntegerField(default=2)
    size_sqm = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("size (m²)")
    )

    # ---- booking rules ------------------------------------------------
    # Sensible Bali-standard defaults - editable per villa.
    check_in_time = models.TimeField(default=time(14, 0))
    check_out_time = models.TimeField(default=time(11, 0))
    min_nights = models.PositiveSmallIntegerField(default=1)
    base_nightly_rate = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text=_("Indicative rate only, in the operator's own reporting currency. "
                     "Real prices per booking live on the booking itself."),
    )
    base_monthly_rate = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text=_("For long-stay guests. Same currency as the nightly rate."),
    )

    # Bilingual free text. Kept as explicit per-language fields rather than
    # gettext because this is operator-authored content, not interface copy.
    description_en = models.TextField(blank=True)
    description_id = models.TextField(blank=True)

    is_listed_publicly = models.BooleanField(
        default=False, help_text=_("Show this villa's own web page and direct booking.")
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("organization", "slug")]

    def __str__(self):
        return self.name


class RoomCategory(TenantOwnedModel):
    """A room type, defined by one villa rather than shared across all of them.

    Villas describe their rooms differently - a two-room guesthouse sells
    "Garden" and "Ocean", an eight-room compound sells "Standard" and
    "Suite" - so the list belongs to the villa, not to the whole product.

    A type is also how rooms get made: the operator names it and says how many
    rooms of it there are, and that many rooms appear, named after it. See
    create_room_type() and set_room_count() below.
    """

    villa = models.ForeignKey(Villa, on_delete=models.CASCADE, related_name="room_categories")
    name = models.CharField(max_length=80)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("villa", "name")]
        verbose_name_plural = _("room categories")

    def __str__(self):
        return f"{self.villa.name} - {self.name}"


class Room(TenantOwnedModel):
    """An individually bookable room within a villa.

    Every villa has at least one - the calendar draws bookings on room rows
    only, so a room-less villa would have nowhere to show its bookings. Rooms
    are created a type at a time (see create_room_type at the bottom of this
    module); existing data was backfilled in
    apps/bookings/migrations/0005_backfill_booking_rooms.py.
    """

    villa = models.ForeignKey(Villa, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=80)
    category = models.ForeignKey(
        RoomCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="rooms",
        help_text=_("One of this villa's own room types."),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        # Grouped by type, then in the order they were created - which is the
        # order they are numbered in ("Deluxe", "Deluxe 2", "Deluxe 3").
        # Sorting by name instead would put "Deluxe 10" before "Deluxe 2", and
        # would also reshuffle the calendar's rows every time one is renamed.
        ordering = ["category__sort_order", "id"]

    def __str__(self):
        return f"{self.villa.name} - {self.name}"

    def clean(self):
        """A room can only be filed under a room type its own villa defines."""
        from django.core.exceptions import ValidationError

        if self.category_id and self.category.villa_id != self.villa_id:
            raise ValidationError({"category": _("Pick a room type that belongs to this villa.")})


class VillaPhoto(TenantOwnedModel):
    """Stored as WebP. Conversion happens on upload - see apps/villas/images.py."""

    villa = models.ForeignKey(Villa, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="villas/%Y/%m/")
    caption_en = models.CharField(max_length=200, blank=True)
    caption_id = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_cover = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]


class Amenity(models.Model):
    """Shared vocabulary across all operators, so it is not tenant-scoped."""

    name_en = models.CharField(max_length=80)
    name_id = models.CharField(max_length=80)
    icon = models.CharField(max_length=40, blank=True)
    villas = models.ManyToManyField(Villa, blank=True, related_name="amenities")

    class Meta:
        ordering = ["name_en"]
        verbose_name_plural = _("amenities")

    def __str__(self):
        return self.name_en


_TRAILING_NUMBER = re.compile(r"\s*\d+$")


def _base_room_name(name: str) -> str:
    """"Deluxe 3" -> "Deluxe": a room's series name, without its number."""
    return _TRAILING_NUMBER.sub("", name).strip() or name.strip()


def next_room_names(villa, category, how_many: int) -> list:
    """The names the next `how_many` rooms of this type should be given.

    Rooms follow the type's first room, which itself starts out named after
    the type: "Deluxe", then "Deluxe 2", "Deluxe 3". Rename that first room
    to "Kenanga" and the next ones become "Kenanga 4", "Kenanga 5" - they
    keep following it, and the number stays the room's place in the type.
    Any name already used elsewhere in the villa is skipped, so two rooms
    never end up with the same name.
    """
    if how_many <= 0:
        return []

    rooms = list(category.rooms.order_by("id")) if category is not None else []
    first = rooms[0] if rooms else None
    if first is not None:
        base = _base_room_name(first.name)
    elif category is not None:
        base = category.name
    else:
        base = DEFAULT_ROOM_TYPE

    taken = {name.strip().casefold() for name in villa.rooms.values_list("name", flat=True)}
    names = []

    # The bare name belongs to the first room, so it is only free while the
    # type has none - after that, numbering picks up where the type left off.
    if first is None and base.casefold() not in taken:
        names.append(base)
        taken.add(base.casefold())

    n = max(len(rooms) + 1, 2)
    while len(names) < how_many:
        candidate = f"{base} {n}"
        if candidate.casefold() not in taken:
            names.append(candidate)
            taken.add(candidate.casefold())
        n += 1
    return names


def add_rooms(villa, category, how_many: int) -> list:
    """Add `how_many` more rooms of one type, named to follow the others."""
    rooms = [
        Room(
            organization_id=villa.organization_id, villa=villa,
            name=name, category=category,
        )
        for name in next_room_names(villa, category, how_many)
    ]
    if rooms:
        # bulk_create sends no post_save, so the count is corrected by hand
        # here rather than by the signal below.
        Room.objects.bulk_create(rooms)
        _sync_bedroom_count(villa)
    return rooms


def create_room_type(villa, name: str, how_many: int = 1):
    """Add a room type to this villa and the rooms that go with it."""
    last = villa.room_categories.order_by("-sort_order").first()
    category = RoomCategory.objects.create(
        organization_id=villa.organization_id, villa=villa, name=name,
        sort_order=(last.sort_order + 1) if last else 0,
    )
    add_rooms(villa, category, how_many)
    return category


def set_room_count(villa, category, count: int) -> tuple:
    """Grow or shrink one room type to `count` rooms. Returns (added, removed).

    Shrinking removes the newest rooms first, and only ones with no bookings
    on them - Booking.room is PROTECT on purpose, so a room holding real
    bookings is kept and an emptier one goes in its place, rather than taking
    those bookings off the calendar. A villa's last room is never removed
    either: the calendar draws bookings on room rows, so a villa with none
    would have nowhere to show them. When too many of a type's rooms are
    booked to reach the number asked for, fewer are removed than asked - the
    caller compares the two and tells the operator what actually happened.
    """
    rooms = list(category.rooms.order_by("id"))
    if count > len(rooms):
        return len(add_rooms(villa, category, count - len(rooms))), 0

    to_remove = len(rooms) - count
    removed = 0
    for room in reversed(rooms):
        if removed >= to_remove or villa.rooms.count() <= 1:
            break
        try:
            room.delete()
        except ProtectedError:
            continue  # still has bookings - keep it, and say so upstream
        removed += 1
    return 0, removed


def default_room_type(villa):
    """The type a one-click "+ Add room" files the new room under."""
    return villa.room_categories.first() or create_room_type(villa, DEFAULT_ROOM_TYPE, how_many=0)


def provision_starter_rooms(villa) -> None:
    """Give a villa that has no rooms yet its first type and rooms.

    For villas created outside the add form - the Django admin, the seed
    command, a shell script - which never got the chance to name their own
    room types. `bedrooms` is read here as "how many rooms to start with",
    the one place it still means anything other than a count.
    """
    if villa.rooms.exists() or villa.room_categories.exists():
        return
    create_room_type(villa, DEFAULT_ROOM_TYPE, how_many=max(villa.bedrooms or 1, 1))


def _sync_bedroom_count(villa) -> None:
    """Point `Villa.bedrooms` at the number of rooms actually on file.

    .update() rather than .save(), so correcting the number can never
    re-enter the villa's own post_save signal.
    """
    count = villa.rooms.filter(is_active=True).count()
    Villa.objects.filter(pk=villa.pk).exclude(bedrooms=count).update(bedrooms=count)
    villa.bedrooms = count


@receiver(post_save, sender=Villa)
def new_villas_start_with_rooms(sender, instance, created, **kwargs):
    """A villa can never exist without a room to book, so one is provided
    here for every route that doesn't define its own.

    The add form does define its own - the operator names the room types
    right on it - so it sets `skip_default_rooms` on the villa and creates
    them itself, in the same transaction. See VillaCreateView.form_valid.
    """
    if not created or getattr(instance, "skip_default_rooms", False):
        return
    provision_starter_rooms(instance)


@receiver([post_save, post_delete], sender=Room)
def bedrooms_follow_rooms(sender, instance, **kwargs):
    """`Villa.bedrooms` is a count of the villa's rooms, so it is rewritten
    whenever one is added or removed - on the calendar, in the admin, or from
    the villa's own rooms panel.

    Skipped when the villa row itself is gone (a cascading villa delete), where
    there is nothing left to keep in step.
    """
    count = Room.objects.filter(villa_id=instance.villa_id, is_active=True).count()
    Villa.objects.filter(pk=instance.villa_id).exclude(bedrooms=count).update(bedrooms=count)

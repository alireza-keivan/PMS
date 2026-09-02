"""Villas, their room types, the rooms themselves, and their photos.

How rooms come into being: the operator names a room type ("Deluxe") and says
how many of them the villa has. That makes the rooms, named after the type -
"Deluxe", "Deluxe 2", "Deluxe 3" - and every one of them can be renamed later.
There is no separate "number of bedrooms" to type in: `Villa.bedrooms` is now
just a cached count of the rooms that exist, kept in step by the signals at
the bottom of this module.

Where each number lives: everything describing a *room* - how big it is, how
many people it sleeps, what it costs, the fewest nights it can be booked for -
belongs to the room type, not to the villa. A whole-villa rental is then just
a villa with one room type holding one room, and a guesthouse with three kinds
of room is the same structure repeated. The villa itself only carries what is
true of the whole property: what it's called, where it is, and when guests
arrive and leave.
"""

import logging
import re
from datetime import time
from urllib.parse import urlparse

import httpx
from django.core.cache import cache
from django.db import models
from django.db.models import ProtectedError
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel, TenantQuerySet

logger = logging.getLogger(__name__)

# Google's old key-free "&output=embed" trick is dead - that path now sends
# back X-Frame-Options: SAMEORIGIN, so it can never be framed on our site,
# and the real replacement (the Maps Embed API) requires a Google Cloud
# billing account just to issue a key. OpenStreetMap's embed needs neither -
# it just wants coordinates, which we pull out of whatever Google Maps link
# the operator pasted in (following a short link first, if that's what it is).
_SHORT_MAPS_LINK_HOSTS = {"maps.app.goo.gl", "goo.gl"}
_LAT_LNG_RE = re.compile(r"(-?\d{1,3}\.\d+),\+?\s*(-?\d{1,3}\.\d+)")

# How far the embedded map extends around the marker, in degrees - about a
# 1km-wide view, enough to place the villa within its neighbourhood.
_MAP_BBOX_DEGREES = 0.005


def _resolve_maps_link(url):
    """Follow a maps.app.goo.gl/goo.gl short link to its real, long URL."""
    if urlparse(url).netloc not in _SHORT_MAPS_LINK_HOSTS:
        return url

    cache_key = f"villas:maps_resolved_url:{url}"
    resolved = cache.get(cache_key)
    if resolved is not None:
        return resolved

    try:
        response = httpx.head(url, follow_redirects=True, timeout=5)
        resolved = str(response.url)
    except httpx.HTTPError:
        logger.warning("Could not resolve short Google Maps link: %s", url)
        resolved = url

    cache.set(cache_key, resolved, timeout=60 * 60 * 24 * 30)
    return resolved


def _osm_embed_url(google_maps_url):
    """An OpenStreetMap embed URL for wherever a pasted Google Maps link points to.

    Returns "" when no coordinates could be read from the link - the caller
    should fall back to just the plain "Open in Maps" link in that case.
    """
    match = _LAT_LNG_RE.search(_resolve_maps_link(google_maps_url))
    if not match:
        return ""
    lat, lng = (float(value) for value in match.groups())

    bbox = (
        f"{lng - _MAP_BBOX_DEGREES},{lat - _MAP_BBOX_DEGREES},"
        f"{lng + _MAP_BBOX_DEGREES},{lat + _MAP_BBOX_DEGREES}"
    )
    return (
        "https://www.openstreetmap.org/export/embed.html"
        f"?bbox={bbox}&marker={lat},{lng}"
    )

# A villa created outside the add form - Django admin, the seed command, a
# shell script - still needs somewhere to put its rooms, so it starts with
# this one type. Deliberately not translated: a room type, like a room name,
# is stored operator data they rename at will, so it must not change meaning
# when the page language changes.
DEFAULT_ROOM_TYPE = "Standard"

# A sanity ceiling on "how many rooms", not a plan limit - it stops a typo
# like 300 from filling a villa with hundreds of rooms nobody asked for.
MAX_ROOMS_PER_TYPE = 60

# Keeps the picture row usable and the villa's storage bill sane - a villa or
# room type never needs more than this many pictures to show what it looks
# like, and a picture this big is almost always an accidental full-res upload.
MAX_PHOTOS_PER_OWNER = 20
MAX_PHOTO_SIZE_MB = 2

# What almost every Bali villa uses. Named here rather than written straight
# into the field, because the add form falls back to them when the operator
# leaves those boxes empty - and both places have to mean the same thing.
DEFAULT_CHECK_IN_TIME = time(14, 0)
DEFAULT_CHECK_OUT_TIME = time(11, 0)


class VillaQuerySet(TenantQuerySet):
    def live(self):
        """Villas that really exist as far as the rest of the app is concerned.

        Leaves out half-finished ones (someone is still on the add form) and
        removed ones. Every screen that lists villas - the picker, the
        calendar, reporting, messaging - and the plan limit itself all go
        through here, so a draft can never turn up on a screen or quietly use
        up one of the operator's paid villa slots.
        """
        return self.filter(is_active=True, is_draft=False)

    def public(self):
        """Villas that have a public web page, and whose operator is still
        running.

        The single gate behind apps.marketing - the public villa pages, the
        direct booking form, and anything else that answers to a visitor with
        no account at all. Written here rather than in each view so there is
        exactly one definition of "published": the villa really exists
        (live()), the operator chose to list it, and their business is still
        switched on. A villa failing any one of those is a 404 out there, not
        a thinner version of the page.
        """
        return self.live().filter(is_listed_publicly=True, organization__is_active=True)


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
    # Not typed in on the villa form - it counts the rooms the villa actually
    # has (see the signals at the bottom of this module). Set on a villa
    # created outside that form, it decides how many rooms it starts with;
    # after that it only ever follows the Room table.
    #
    # How many guests a villa sleeps, how big its rooms are and what they cost
    # are not stored here at all - they belong to each room type. See `sleeps`
    # below and the RoomCategory fields.
    bedrooms = models.PositiveSmallIntegerField(default=1)

    # ---- booking rules ------------------------------------------------
    # Optional on the form, but never empty on file: left blank they fall back
    # to these Bali-standard times, so no screen ever has to show a check-in
    # time that isn't there.
    check_in_time = models.TimeField(default=DEFAULT_CHECK_IN_TIME)
    check_out_time = models.TimeField(default=DEFAULT_CHECK_OUT_TIME)

    # Bilingual free text. Kept as explicit per-language fields rather than
    # gettext because this is operator-authored content, not interface copy.
    description_en = models.TextField(blank=True)
    description_id = models.TextField(blank=True)

    is_listed_publicly = models.BooleanField(
        default=False, help_text=_("Show this villa's own web page and direct booking.")
    )
    is_active = models.BooleanField(default=True)

    # Set the moment the first step of the add form is saved, cleared when the
    # operator finishes the second one. A draft is a real row - so photos have
    # somewhere to go and nothing typed is ever lost - but it is invisible
    # everywhere else in the app. See VillaQuerySet.live().
    is_draft = models.BooleanField(default=False)

    objects = VillaQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        unique_together = [("organization", "slug")]

    def __str__(self):
        return self.name

    @property
    def google_maps_embed_url(self) -> str:
        """The OpenStreetMap URL for the public villa page's map iframe.

        Empty when there's no pasted google_maps_url, or no coordinates could
        be read from it - callers should hide the map and fall back to the
        plain "Open in Maps" link either way.
        """
        if not self.google_maps_url:
            return ""
        return _osm_embed_url(self.google_maps_url)

    @property
    def sleeps(self) -> int:
        """How many guests the whole villa takes, added up from its rooms.

        Each room type says how many guests one of its rooms sleeps, so the
        villa's total is that number times how many rooms of the type there
        are. Worked out on demand rather than stored, so it can never fall out
        of step with the rooms themselves.
        """
        return sum(
            category.max_guests * category.rooms.count()
            for category in self.room_categories.all()
        )


class RoomCategory(TenantOwnedModel):
    """A room type, defined by one villa rather than shared across all of them.

    Villas describe their rooms differently - a two-room guesthouse sells
    "Garden" and "Ocean", an eight-room compound sells "Standard" and
    "Suite" - so the list belongs to the villa, not to the whole product.

    A type is also how rooms get made: the operator names it and says how many
    rooms of it there are, and that many rooms appear, named after it. See
    create_room_type() and set_room_count() below.

    There is no `room_count` column here on purpose. The calendar draws
    bookings on room rows, so the rooms have to exist as real records - and a
    number stored beside them would start drifting from them the first time a
    room was added or removed anywhere else. "How many rooms" is asked for on
    the form and answered by set_room_count(), which makes or removes the real
    rooms; reading it back is just `category.rooms.count()`.
    """

    villa = models.ForeignKey(Villa, on_delete=models.CASCADE, related_name="room_categories")
    name = models.CharField(max_length=80)
    sort_order = models.PositiveSmallIntegerField(default=0)

    # ---- what a room of this type is like -------------------------------
    size_sqm = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("size (m²)")
    )
    max_guests = models.PositiveSmallIntegerField(default=2)
    amenities = models.ManyToManyField(
        "Amenity", blank=True, related_name="room_categories",
    )

    # ---- what it costs --------------------------------------------------
    # Whole rupiah, no decimal places: a villa night in Bali is priced in
    # hundreds of thousands and nobody quotes 1.500.000,50. Stored as plain
    # integers and shown with thousand separators on screen.
    nightly_rate = models.PositiveBigIntegerField(
        null=True, blank=True, help_text=_("Price for one night, in rupiah."),
    )
    monthly_rate = models.PositiveBigIntegerField(
        null=True, blank=True, help_text=_("Price for a whole month, in rupiah."),
    )
    minimum_nights = models.PositiveSmallIntegerField(default=1)

    # Lets the second and later room types skip their own photo shoot and
    # just show the villa's first room type's pictures instead. Meaningless
    # on the first room type itself - there is nothing before it to copy.
    use_first_category_photos = models.BooleanField(
        default=False,
        help_text=_("Show the first room type's photos here instead of its own."),
    )

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("villa", "name")]
        verbose_name_plural = _("room categories")

    def __str__(self):
        return f"{self.villa.name} - {self.name}"

    @property
    def room_count(self) -> int:
        """How many rooms of this type the villa has. Counted, never stored."""
        return self.rooms.count()

    @property
    def display_photos(self):
        """The photos to actually show for this room type.

        Its own, unless it's opted into showing the first room type's
        instead - in which case its own upload box is never used at all.
        """
        if self.use_first_category_photos:
            first = self.villa.room_categories.first()
            if first is not None and first.pk != self.pk:
                return first.photos.live()
        return self.photos.live()


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


class PhotoQuerySet(TenantQuerySet):
    """Pictures on the villa form are staged, not saved the second they're picked.

    An upload is written to storage right away - the bytes have to go
    somewhere - but it is written as `is_pending`, and a removal only sets
    `pending_delete`. Neither counts as real until the operator presses Save
    on the page, which is when commit_photos in views.py turns pending into
    live and really deletes what was marked. Walking away instead leaves the
    villa exactly as it was, and prune_staged_photos sweeps the leftovers.

      .live()         - what the villa really has, for everywhere else. A
                        picture marked for removal is still in here: until
                        Save it is still one of the villa's pictures, so an
                        abandoned edit changes nothing anyone else can see.
      .on_the_form()  - what the person editing should see right now:
                        live pictures plus their own not-yet-saved additions,
                        minus the ones they just took off
    """

    def live(self):
        return self.filter(is_pending=False)

    def on_the_form(self):
        return self.filter(pending_delete=False)


class StagedPhotoFields(models.Model):
    """The two staging flags, shared by villa and room-type pictures."""

    is_pending = models.BooleanField(
        default=False,
        help_text=_("Uploaded but not saved yet - discarded if the page is left."),
    )
    pending_delete = models.BooleanField(
        default=False,
        help_text=_("Taken off the form but not saved yet - kept until Save."),
    )

    objects = PhotoQuerySet.as_manager()

    class Meta:
        abstract = True


class VillaPhoto(StagedPhotoFields, TenantOwnedModel):
    """Stored as WebP. Conversion happens on upload - see apps/villas/images.py."""

    villa = models.ForeignKey(Villa, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="villas/%Y/%m/")
    caption_en = models.CharField(max_length=200, blank=True)
    caption_id = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_cover = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"Photo {self.pk} of {self.villa}"


class RoomCategoryPhoto(StagedPhotoFields, TenantOwnedModel):
    """Photos of one kind of room, as opposed to the property as a whole.

    Same rules as VillaPhoto: stored as WebP, converted on upload.
    """

    category = models.ForeignKey(
        RoomCategory, on_delete=models.CASCADE, related_name="photos"
    )
    image = models.ImageField(upload_to="room-types/%Y/%m/")
    caption_en = models.CharField(max_length=200, blank=True)
    caption_id = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_cover = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"Photo {self.pk} of {self.category}"


class Amenity(models.Model):
    """Something a room comes with - a pool, air conditioning, a rice field view.

    Two kinds live in the same table. The ones seeded with the product have no
    organization and are offered to everybody. The ones an operator types in
    themselves carry their organization, so they come back as a ready-made
    option next time without ever showing up on another operator's list.

    Not a TenantOwnedModel, because the shared ones deliberately belong to
    nobody - `organization` has to be allowed to be empty.
    """

    name_en = models.CharField(max_length=80)
    name_id = models.CharField(max_length=80)
    icon = models.CharField(max_length=40, blank=True)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE, null=True, blank=True, related_name="amenities",
        help_text=_("Leave empty for an amenity every operator can pick."),
    )

    class Meta:
        ordering = ["name_en"]
        verbose_name_plural = _("amenities")

    def __str__(self):
        return self.name_en

    @classmethod
    def available_to(cls, organization):
        """The shared list plus this operator's own additions."""
        return cls.objects.filter(
            models.Q(organization__isnull=True) | models.Q(organization=organization)
        )


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
        logger.info(
            "Added %s room(s) to villa %s (%s) under room type %s: %s",
            len(rooms), villa.pk, villa.name,
            category.pk if category else None, [room.name for room in rooms],
        )
    return rooms


def rename_rooms_after_type(category, old_name: str, new_name: str) -> int:
    """Bring a room type's rooms along when the type itself is renamed.

    A room starts out named after its type - "Deluxe", "Deluxe 2", "Deluxe 3" -
    so renaming the type to "Garden" has to rename those too. Without this a
    villa ends up with a room type called Garden whose rooms are all still
    called Deluxe, which is exactly the confusion the naming is meant to avoid.

    A room the operator renamed themselves - "Kenanga", say - is left alone.
    Their name for it was deliberate, and this is not the place to overwrite
    it. Each room keeps its number, so "Deluxe 3" becomes "Garden 3".
    """
    old, new = old_name.strip(), new_name.strip()
    if not old or not new or old.casefold() == new.casefold():
        return 0

    taken = {name.strip().casefold() for name in category.villa.rooms.values_list("name", flat=True)}
    renamed = 0
    for room in category.rooms.order_by("id"):
        base = _base_room_name(room.name)
        if base.casefold() != old.casefold():
            continue  # renamed by hand - not ours to touch
        candidate = new + room.name[len(base):]
        if candidate.casefold() in taken:
            continue  # that name is already in use elsewhere in the villa
        taken.discard(room.name.strip().casefold())
        taken.add(candidate.casefold())
        room.name = candidate
        room.save(update_fields=["name"])
        renamed += 1

    if renamed:
        logger.info(
            "Renamed %s room(s) on villa %s to follow room type %s: %s -> %s",
            renamed, category.villa_id, category.pk, old, new,
        )
    return renamed


def create_room_type(villa, name: str, how_many: int = 1):
    """Add a room type to this villa and the rooms that go with it."""
    last = villa.room_categories.order_by("-sort_order").first()
    category = RoomCategory.objects.create(
        organization_id=villa.organization_id, villa=villa, name=name,
        sort_order=(last.sort_order + 1) if last else 0,
    )
    logger.info(
        "Created room type %s (%s) on villa %s (%s) with %s room(s)",
        category.pk, name, villa.pk, villa.name, how_many,
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
            logger.info(
                "Kept room %s (%s) on villa %s - it still has bookings on it",
                room.pk, room.name, villa.pk,
            )
            continue  # still has bookings - keep it, and say so upstream
        removed += 1
    if removed:
        logger.info(
            "Removed %s of the %s room(s) asked for from room type %s on villa %s",
            removed, to_remove, category.pk, villa.pk,
        )
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

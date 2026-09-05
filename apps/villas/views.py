"""The villa picker, and the two-step form behind "add a villa".

Why two steps and a draft row: step 1 is about the property, step 2 is about
its rooms, and the two ask for genuinely different things. Rather than hold
step 1 in the session, finishing it saves a real villa marked `is_draft`. That
buys two things - the operator can close the browser and come back to it, and
each room type on step 2 is already a real row, so a photo has somewhere to go
the moment it is picked. A draft is invisible everywhere else in the app and
does not use up a villa slot on the operator's plan: see VillaQuerySet.live().
"""

import json
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.http import HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, TemplateView, View
from PIL import Image

from apps.bookings.models import Booking
from apps.core.utils import safe_next
from apps.marketing.forms import ExperienceForm
from apps.marketing.models import Experience
from apps.organizations.mixins import ManagerRequiredMixin
from apps.organizations.permissions import is_manager
from apps.organizations.scoping import scoped_villas
from apps.villas.forms import (
    BALI_AREAS,
    CustomAmenityForm,
    RoomCategoryFormSet,
    VillaForm,
)
from apps.villas.images import WebPUnavailable, to_webp
from apps.villas.models import (
    DEFAULT_ROOM_TYPE,
    MAX_PHOTO_SIZE_MB,
    MAX_PHOTOS_PER_OWNER,
    MAX_ROOMS_PER_TYPE,
    MAX_VILLA_AMENITIES,
    MIN_PHOTO_WIDTH_PX,
    Amenity,
    Room,
    RoomCategory,
    RoomCategoryPhoto,
    Villa,
    VillaPhoto,
    add_rooms,
    create_room_type,
    default_room_type,
    rename_rooms_after_type,
    set_room_count,
)

logger = logging.getLogger(__name__)

OCCUPYING_STATUSES = [Booking.Status.CONFIRMED, Booking.Status.BLOCKED]

# The name the room blocks are submitted under. Short on purpose - it ends up
# in every field name on step 2 ("rooms-0-name"), including the ones the
# add-a-block view has to renumber below.
ROOMS_PREFIX = "rooms"


class VillaListView(LoginRequiredMixin, TemplateView):
    template_name = "villas/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization

        if org is None:
            context["no_organization"] = True
            return context

        today = timezone.localdate()
        # Counted from the Room table rather than read off Villa.bedrooms, so
        # this card and the booking calendar can never show different numbers
        # of rooms for the same villa.
        scoped, _membership = scoped_villas(self.request)
        villas = list(
            Villa.objects.filter(id__in=[v.id for v in scoped])
            .annotate(room_count=Count("rooms", filter=Q(rooms__is_active=True)))
            .prefetch_related("room_categories")
            .order_by("name")
        )

        # A villa has several rooms, so it's only "unavailable" once every one
        # of its rooms is occupied today - a single booked room out of many
        # should still show "available now". Once fully booked, "available
        # from" is when the last of today's occupying bookings checks out
        # (the earliest checkout only frees one room, not the villa).
        occupied_rooms_by_villa = {}
        latest_checkout_by_villa = {}
        current_bookings = Booking.objects.filter(
            organization=org,
            villa_id__in=[v.id for v in villas],
            check_in__lte=today, check_out__gt=today,
            status__in=OCCUPYING_STATUSES,
        ).values_list("villa_id", "room_id", "check_out")
        for villa_id, room_id, check_out in current_bookings:
            occupied_rooms_by_villa.setdefault(villa_id, set()).add(room_id)
            if villa_id not in latest_checkout_by_villa or check_out > latest_checkout_by_villa[villa_id]:
                latest_checkout_by_villa[villa_id] = check_out

        for villa in villas:
            occupied = occupied_rooms_by_villa.get(villa.id, set())
            fully_booked = villa.room_count > 0 and len(occupied) >= villa.room_count
            villa.available_from = latest_checkout_by_villa.get(villa.id) if fully_booked else None

        manager = is_manager(self.request.user)
        context.update(
            villas=villas,
            # Villas somebody started adding and never finished. Half-created
            # villas have no assigned staff yet, and finishing/discarding one
            # is a structural action, so this list is Manager-only.
            drafts=(
                list(org.villas.filter(is_draft=True, is_active=True).order_by("-updated_at"))
                if manager else []
            ),
            can_add_villa=org.can_add_villa,
            villa_limit=org.villa_limit,
            is_manager=manager,
        )
        return context


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _get_org_villa(request, slug, drafts_too=True):
    org = request.organization
    villas = Villa.objects.filter(organization=org) if org else Villa.objects.none()
    if not drafts_too:
        villas = villas.filter(is_draft=False)
    return get_object_or_404(villas, slug=slug)


def _unique_slug(org, name: str) -> str:
    base = slugify(name) or "villa"
    slug = base
    suffix = 2
    while org.villas.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _villa_photo_count(villa):
    """How many pictures already count against a villa's shared 20-photo limit.

    The limit is per villa, not per room - it adds up the villa's own photos
    and every room type's photos underneath it.
    """
    if villa is None or villa.pk is None:
        return 0
    room_total = RoomCategoryPhoto.objects.filter(
        category__villa=villa,
    ).on_the_form().count()
    return villa.photos.on_the_form().count() + room_total


def _check_photo_limits(files, existing_count):
    """Catch too-many, too-big and too-small pictures before any conversion.

    Checked ahead of _convert_photos so a violation is reported plainly
    instead of surfacing as a WebP conversion failure.

    The minimum width is the fussy one, and it is deliberate: the villa page
    serves a 1600px hero, so a small picture gets blown up and looks soft. The
    file handles are rewound after measuring, because _convert_photos reads
    the very same ones straight afterwards.
    """
    if existing_count + len(files) > MAX_PHOTOS_PER_OWNER:
        return _("You can only have up to %(max)s pictures. Remove some before adding more.") % {
            "max": MAX_PHOTOS_PER_OWNER,
        }
    oversized = [f.name for f in files if f.size > MAX_PHOTO_SIZE_MB * 1024 * 1024]
    if oversized:
        return _("These pictures are bigger than %(max)s MB: %(names)s. Use smaller files.") % {
            "max": MAX_PHOTO_SIZE_MB, "names": ", ".join(oversized),
        }

    unreadable, too_small = [], []
    for uploaded in files:
        try:
            # Not closed, and not a `with` block: closing the Pillow image
            # would close the upload's own handle, and _convert_photos still
            # has to read it. Only the header is read to get the size.
            width = Image.open(uploaded).width
        except Exception:
            unreadable.append(uploaded.name)
            continue
        finally:
            uploaded.seek(0)
        if width < MIN_PHOTO_WIDTH_PX:
            too_small.append(uploaded.name)

    if unreadable:
        return _("These files are not pictures: %(names)s. Upload photos only.") % {
            "names": ", ".join(unreadable),
        }
    if too_small:
        return _(
            "These pictures are too small to look sharp on the villa page: "
            "%(names)s. Please upload bigger ones, at least %(min)s pixels wide."
        ) % {"names": ", ".join(too_small), "min": MIN_PHOTO_WIDTH_PX}
    return None


def _parse_crops(post, expected: int):
    """Read the frames the operator lined each picture up in, off the form.

    The cropper in static/js/photo_cropper.js posts one JSON list alongside
    the files, in the same order: either a {x, y, width, height} box, all
    fractions of the picture, or null for a picture whose frame was left
    alone. Anything unreadable comes back as a list of Nones rather than an
    error - a picture with no chosen frame simply falls back to the middle of
    itself, which is what the villa page always did before this existed. A
    bad crop must never be the reason an upload fails.
    """
    raw = post.get("crops")
    if not raw:
        return [None] * expected
    try:
        boxes = json.loads(raw)
        if not isinstance(boxes, list):
            raise ValueError("crops must be a list")
        parsed = [
            None if box is None else (
                float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
            )
            for box in boxes
        ]
    except (ValueError, TypeError, KeyError):
        logger.warning("Ignoring unreadable crop boxes on an upload: %r", raw[:200])
        return [None] * expected

    # Length is not trusted either: the browser could have sent fewer or more
    # than the files that actually arrived.
    parsed = parsed[:expected]
    return parsed + [None] * (expected - len(parsed))


def _convert_photos(files):
    """Turn what was uploaded into WebP, before anything at all is written.

    Done first, and separately from storing it, so a picture that can't be
    converted stops the whole thing while there is still nothing to undo.
    Per CLAUDE.md a failed conversion is never papered over with a JPEG - this
    raises WebPUnavailable and the caller says so plainly instead.
    """
    return [to_webp(uploaded) for uploaded in files]


def _store_photos(organization, owner, webp_files, photo_model, owner_field, pending=False, crops=None):
    """File already-converted pictures against a villa or a room type.

    `pending=True` means these were picked on a form that hasn't been saved
    yet: the file is written now, but the row is marked as not-yet-real and
    only counts once commit_photos runs. See PhotoQuerySet in models.py.

    Order and cover are worked out here for the straight-to-live case, and
    re-worked by _resequence_photos at commit time for the staged one.

    `crops` lines up one-for-one with `webp_files` - the frame the operator
    dragged each picture into, or None to keep the middle of it.
    """
    start = photo_model.objects.filter(**{owner_field: owner}).count()
    crops = crops or [None] * len(webp_files)
    saved = []
    for offset, webp in enumerate(webp_files):
        photo = photo_model(
            organization=organization, image=webp, sort_order=start + offset,
            is_cover=(start + offset == 0), is_pending=pending, **{owner_field: owner},
        )
        photo.set_crop(crops[offset])
        photo.save()
        saved.append(photo)
    if saved:
        logger.info(
            "Stored %s photo(s) as WebP for %s %s - pending=%s",
            len(saved), owner_field, owner.pk, pending,
        )
    return saved


def _resequence_photos(photos):
    """Put the surviving pictures back in a clean 0, 1, 2 order, first as cover.

    Needed after a commit, because staged rows were numbered as they arrived
    and the cover may well have been one of the pictures just removed.
    """
    for position, photo in enumerate(photos):
        wanted_cover = position == 0
        if photo.sort_order != position or photo.is_cover != wanted_cover:
            photo.sort_order = position
            photo.is_cover = wanted_cover
            photo.save(update_fields=["sort_order", "is_cover", "updated_at"])


def _stage_removal(photo, owner_label, owner_pk):
    """Take a picture off the form without really deleting it yet.

    One exception: a picture that was only added a moment ago and never saved
    is thrown away for real, because there is nothing behind it to go back to.
    """
    if photo.is_pending:
        photo.delete()
        logger.info("Discarded a not-yet-saved photo on %s %s", owner_label, owner_pk)
        return
    photo.pending_delete = True
    photo.save(update_fields=["pending_delete", "updated_at"])
    logger.info("Photo %s marked for removal on %s %s - waiting on Save", photo.pk, owner_label, owner_pk)


def _photo_grid(request, context):
    """Hand the picture row back to HTMX, and tell the page it changed.

    The HX-Trigger is what wakes the Save button up: the pictures live outside
    the form's own fields, so nothing else on the page would notice.
    """
    response = render(request, "villas/_photo_grid.html", context)
    response["HX-Trigger"] = "photos-changed"
    return response


def commit_photos(owner, photo_model, owner_field):
    """Make this villa's or room type's staged picture changes real.

    Called from the Save on the page the pictures were picked on, inside that
    save's own transaction, so pressing Save applies the picture changes and
    the typed changes together or not at all.
    """
    rows = photo_model.objects.filter(**{owner_field: owner})

    going = list(rows.filter(pending_delete=True))
    for photo in going:
        photo.delete()
    arriving = rows.filter(is_pending=True).update(is_pending=False)

    if going or arriving:
        _resequence_photos(list(rows.live()))
        logger.info(
            "Committed photo changes on %s %s - %s added, %s removed",
            owner_field, owner.pk, arriving, len(going),
        )
    return arriving, len(going)


def _blocks_from_post(post, drop_index=None):
    """Pull each room block's typed values out of a submitted step-2 form.

    Adding or removing a block has to hand the page back with everything else
    still filled in, and Django numbers a formset's fields strictly 0, 1, 2 -
    a gap in the middle makes it stop reading. So the surviving blocks are
    read out here and renumbered by _formset_data below, which is what lets a
    block be removed from the middle without losing the ones after it.
    """
    try:
        total = int(post.get(f"{ROOMS_PREFIX}-TOTAL_FORMS", 0))
    except (TypeError, ValueError):
        total = 0

    blocks = []
    for index in range(total):
        if index == drop_index:
            continue
        start = f"{ROOMS_PREFIX}-{index}-"
        block = {key[len(start):]: post.getlist(key) for key in post if key.startswith(start)}
        if block:
            blocks.append(block)
    return blocks


def _formset_data(blocks):
    """Turn renumbered blocks back into something a formset can read."""
    data = QueryDict(mutable=True)
    data[f"{ROOMS_PREFIX}-TOTAL_FORMS"] = str(len(blocks))
    data[f"{ROOMS_PREFIX}-INITIAL_FORMS"] = str(len(blocks))
    data[f"{ROOMS_PREFIX}-MIN_NUM_FORMS"] = "0"
    data[f"{ROOMS_PREFIX}-MAX_NUM_FORMS"] = "1000"
    for index, block in enumerate(blocks):
        for name, values in block.items():
            data.setlist(f"{ROOMS_PREFIX}-{index}-{name}", values)
    return data


def _room_formset(villa, organization, data=None):
    return RoomCategoryFormSet(
        data, instance=villa, prefix=ROOMS_PREFIX, organization=organization,
    )


def _rooms_context(villa, organization, formset, hide_errors=False):
    return {
        "villa": villa,
        "organization": organization,
        "formset": formset,
        # Blocks re-rendered after adding or removing one are showing work in
        # progress, not a rejected submission - turning every half-filled box
        # red at that moment would be noise, not help. Phrased as "hide"
        # rather than "show" so a template that forgets to pass it still shows
        # errors, which is the safer way round to be wrong.
        "hide_errors": hide_errors,
        "max_rooms_per_type": MAX_ROOMS_PER_TYPE,
        # Only amenities this operator typed in themselves can be removed -
        # never one of the shared, built-in ones. Stringified so the template
        # can compare it straight against a checkbox's value.
        "custom_amenity_ids": {
            str(pk) for pk in Amenity.objects.filter(organization=organization).values_list("pk", flat=True)
        } if organization else set(),
    }


def _next_type_name(villa) -> str:
    """A name for a freshly added block that isn't taken yet."""
    taken = {name.casefold() for name in villa.room_categories.values_list("name", flat=True)}
    if DEFAULT_ROOM_TYPE.casefold() not in taken:
        return DEFAULT_ROOM_TYPE
    n = 2
    while f"{DEFAULT_ROOM_TYPE} {n}".casefold() in taken:
        n += 1
    return f"{DEFAULT_ROOM_TYPE} {n}"


# ---------------------------------------------------------------------------
# Adding a villa - step 1, about the property
# ---------------------------------------------------------------------------


class VillaDetailsView(ManagerRequiredMixin, View):
    """Step 1. Also the "Back" destination from step 2, where it loads the
    draft's saved answers so nothing typed earlier is lost.
    """

    template_name = "villas/add_details.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)  # LoginRequiredMixin handles it

        self.organization = request.organization
        if self.organization is None:
            return redirect("villas:list")  # shows the "no organization" state there

        self.villa = _get_org_villa(request, kwargs["slug"]) if kwargs.get("slug") else None

        # Checked here so a direct POST can't bypass a disabled button - the
        # button being hidden is a courtesy, not the actual enforcement. A
        # draft already underway is let through: it is being finished, not
        # added, and it isn't counted against the limit either.
        if self.villa is None and not self.organization.can_add_villa:
            messages.error(
                request,
                _("You've reached your plan's limit of %(limit)s villas. Contact us to add more.")
                % {"limit": self.organization.villa_limit},
            )
            return redirect("villas:list")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, slug=None):
        return self._render(VillaForm(instance=self.villa, organization=self.organization))

    def post(self, request, slug=None):
        form = VillaForm(request.POST, instance=self.villa, organization=self.organization)
        if not form.is_valid():
            return self._render(form)

        # Checked and converted before a single row is written, so a picture
        # that breaks a limit or can't be turned into WebP stops this while
        # there is still nothing to undo.
        photo_files = request.FILES.getlist("photos")
        limit_error = _check_photo_limits(photo_files, _villa_photo_count(self.villa))
        if limit_error:
            form.add_error(None, limit_error)
            return self._render(form)
        try:
            webp_photos = _convert_photos(photo_files)
        except WebPUnavailable:
            logger.exception("WebP conversion is unavailable - villa form for %s", self.organization.pk)
            form.add_error(None, _(
                "Those pictures couldn't be processed. Try different ones, or "
                "carry on without them and add them later."
            ))
            return self._render(form)

        with transaction.atomic():
            villa = form.save(commit=False)
            if villa.pk is None:
                villa.organization = self.organization
                villa.slug = _unique_slug(self.organization, villa.name)
                villa.is_draft = True
                # Room types are named on step 2, so this villa must not also
                # be handed the starter room every other route gets. See
                # new_villas_start_with_rooms in models.py.
                villa.skip_default_rooms = True
            villa.save()
            form.save_m2m()

            if not villa.room_categories.exists():
                create_room_type(villa, DEFAULT_ROOM_TYPE, how_many=1)
            if webp_photos:
                # The very first save of a brand-new villa: these rode along
                # with the form because there was no villa to attach them to
                # when they were picked, so they are already what was asked
                # for and go straight in.
                _store_photos(
                    self.organization, villa, webp_photos, VillaPhoto, "villa",
                    crops=_parse_crops(request.POST, len(webp_photos)),
                )
            # Anything picked or taken off through the picture row on this
            # page has been waiting for exactly this moment.
            commit_photos(villa, VillaPhoto, "villa")

        logger.info(
            "Villa %s (%s) saved at step 1 by user %s - draft=%s",
            villa.pk, villa.name, request.user.pk, villa.is_draft,
        )
        if villa.is_draft:
            return redirect("villas:rooms", slug=villa.slug)
        messages.success(request, _("Saved"))
        return redirect("villas:edit", slug=villa.slug)

    def _render(self, form):
        context = {
            "form": form,
            "villa": self.villa,
            "organization": self.organization,
            "areas": BALI_AREAS,
            "step": 1,
            "max_amenities": MAX_VILLA_AMENITIES,
            # Only amenities this operator typed in themselves can be removed -
            # never one of the shared, built-in ones.
            "custom_amenity_ids": {
                str(pk) for pk in
                Amenity.objects.filter(organization=self.organization).values_list("pk", flat=True)
            },
        }
        return render(self.request, self.template_name, context)


# ---------------------------------------------------------------------------
# Adding a villa - step 2, the rooms
# ---------------------------------------------------------------------------


class VillaRoomsView(ManagerRequiredMixin, View):
    """The room blocks - step 2 when adding, and step 2 of editing too once
    the villa is real. One view either way, because it is the same work.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.organization = request.organization
        if self.organization is None:
            return redirect("villas:list")
        self.villa = _get_org_villa(request, kwargs["slug"])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, slug):
        return self._render(_room_formset(self.villa, self.organization))

    def post(self, request, slug):
        formset = _room_formset(self.villa, self.organization, data=request.POST)
        if not formset.is_valid():
            logger.info("Room blocks rejected for villa %s: %s", self.villa.pk, formset.errors)
            return self._render(formset)

        was_draft = self.villa.is_draft
        kept_anywhere = 0
        with transaction.atomic():
            # Renames happen before anything is added or removed, so rooms
            # created in this same save follow the type's new name rather than
            # the one it is about to stop having.
            for form in formset.forms:
                was_called = form.initial.get("name")
                if was_called:
                    rename_rooms_after_type(
                        form.instance, was_called, form.cleaned_data["name"],
                    )

            # Saves each block's own details, its amenities included.
            formset.save()
            for form in formset.forms:
                category = form.instance
                wanted = form.cleaned_data["room_count"]
                had = category.rooms.count()
                _added, removed = set_room_count(self.villa, category, wanted)
                kept_anywhere += max((had - wanted) - removed, 0)

            # Pictures picked or removed on this page are only staged until
            # now - this is the press of Save they were waiting for.
            for category in self.villa.room_categories.all():
                commit_photos(category, RoomCategoryPhoto, "category")

            if was_draft:
                self.villa.is_draft = False
                self.villa.save(update_fields=["is_draft", "updated_at"])

        if kept_anywhere:
            # Honest rather than silent: a room with bookings on it stays, and
            # the number on screen has to say so instead of pretending.
            messages.error(request, _(
                "%(count)s room(s) were kept because they still have bookings on them."
            ) % {"count": kept_anywhere})

        logger.info(
            "Villa %s (%s) rooms saved by user %s - %s room type(s), was a draft: %s",
            self.villa.pk, self.villa.name, request.user.pk,
            formset.total_form_count(), was_draft,
        )
        if was_draft:
            messages.success(request, _("%(name)s is ready.") % {"name": self.villa.name})
            return redirect("villas:list")
        messages.success(request, _("Saved"))
        return redirect("villas:rooms", slug=self.villa.slug)

    def _render(self, formset):
        context = _rooms_context(self.villa, self.organization, formset)
        context["step"] = 2
        return render(self.request, "villas/add_rooms.html", context)


class RoomBlocksPartialMixin:
    """Renders the whole run of room blocks back to HTMX after one changed.

    The blocks come back as a set rather than one at a time because Django
    numbers a formset's fields 0, 1, 2 with no gaps allowed - so removing the
    middle one means renumbering the rest, and appending one means the page's
    hidden "how many blocks are there" counter has to move too. Handing back
    the whole run keeps all of that in one place.
    """

    def render_blocks(self, request, villa, organization, blocks, error=None, note=None):
        formset = _room_formset(villa, organization, data=_formset_data(blocks))
        context = _rooms_context(villa, organization, formset, hide_errors=True)
        # Shown at the top of the blocks rather than through Django's message
        # bar: only this part of the page is being swapped, so a message
        # queued for the next full page load would arrive far too late.
        context["blocks_error"] = error
        context["blocks_note"] = note
        return render(request, "villas/_room_blocks.html", context)


class RoomCategoryCreateView(ManagerRequiredMixin, RoomBlocksPartialMixin, View):
    """"Add another room type" - creates a real room type straight away.

    Real rather than a blank block on the page, so its photos have somewhere
    to go the moment they are picked.

    Whatever was ticked on the first block comes pre-ticked here. Most kinds of
    room in one villa share the same things - pool, WiFi, air conditioning -
    and ticking the same eight boxes over again is exactly the busywork this
    product exists to take away. Anything that doesn't apply can be unticked.
    """

    def post(self, request, slug):
        villa = _get_org_villa(request, slug)
        organization = request.organization

        with transaction.atomic():
            category = create_room_type(villa, _next_type_name(villa), how_many=1)
            first_block = _blocks_from_post(request.POST)
            inherited = first_block[0].get("amenities", []) if first_block else []
            if inherited:
                category.amenities.set(
                    Amenity.available_to(organization).filter(pk__in=inherited)
                )

        logger.info(
            "Added room type %s to villa %s, carrying over %s amenity tick(s)",
            category.pk, villa.pk, len(inherited),
        )

        if request.headers.get("HX-Request"):
            blocks = _blocks_from_post(request.POST)
            blocks.append({
                "id": [str(category.pk)],
                "name": [category.name],
                "room_count": ["1"],
                "max_guests": [str(category.max_guests)],
                "minimum_nights": [str(category.minimum_nights)],
                "amenities": list(inherited),
            })
            return self.render_blocks(request, villa, organization, blocks)
        return redirect("villas:edit", slug=villa.slug)


class RoomCategoryDeleteView(ManagerRequiredMixin, RoomBlocksPartialMixin, View):
    """Remove a room type.

    Its rooms move to another one of the villa's types rather than being
    deleted - a room can hold real bookings, so tidying up a label must never
    take those off the calendar. A villa's last room type can't be removed at
    all: its rooms would have nowhere to go, and the calendar draws bookings
    on room rows.
    """

    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        organization = request.organization
        category = get_object_or_404(RoomCategory.objects.filter(villa=villa), pk=pk)
        moved_to = villa.room_categories.exclude(pk=category.pk).first()
        in_use = category.rooms.count()

        if moved_to is None:
            message = _("A villa needs at least one room type - add another before removing this one.")
            logger.info("Refused to remove the last room type on villa %s", villa.pk)
            if request.headers.get("HX-Request"):
                return self.render_blocks(
                    request, villa, organization,
                    _blocks_from_post(request.POST), error=message,
                )
            messages.error(request, message)
            return redirect("villas:edit", slug=villa.slug)

        drop_index = self._index_of(request.POST, category.pk)
        with transaction.atomic():
            if in_use:
                category.rooms.update(category=moved_to)
            category.delete()

        logger.info(
            "Removed room type %s from villa %s; %s room(s) moved to %s",
            pk, villa.pk, in_use, moved_to.pk,
        )
        # A room can hold real bookings, so it is never thrown away with its
        # label - it is moved, and the operator is told where it went.
        note = _("%(count)s room(s) moved to %(name)s.") % {
            "count": in_use, "name": moved_to.name,
        } if in_use else None

        if request.headers.get("HX-Request"):
            return self.render_blocks(
                request, villa, organization,
                _blocks_from_post(request.POST, drop_index), note=note,
            )
        if note:
            messages.success(request, note)
        return redirect("villas:edit", slug=villa.slug)

    @staticmethod
    def _index_of(post, pk):
        """Which submitted block holds this room type, so it can be dropped."""
        try:
            total = int(post.get(f"{ROOMS_PREFIX}-TOTAL_FORMS", 0))
        except (TypeError, ValueError):
            return None
        for index in range(total):
            if post.get(f"{ROOMS_PREFIX}-{index}-id") == str(pk):
                return index
        return None


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------


class RoomPhotoUploadView(ManagerRequiredMixin, View):
    """Pictures of one kind of room, held aside until the page is saved.

    The file itself is written straight away - the bytes have to go somewhere,
    and the block they belong to is already a real room type, which is the
    whole reason step 1 saves a draft instead of holding everything in memory.
    But the row is marked pending, so it only becomes one of the room's real
    pictures when Save is pressed. See PhotoQuerySet in models.py.
    """

    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        category = get_object_or_404(RoomCategory.objects.filter(villa=villa), pk=pk)
        files = request.FILES.getlist("photos")

        error = None
        if files:
            error = _check_photo_limits(files, _villa_photo_count(villa))
            if not error:
                try:
                    _store_photos(
                        request.organization, category, _convert_photos(files),
                        RoomCategoryPhoto, "category", pending=True,
                        crops=_parse_crops(request.POST, len(files)),
                    )
                except WebPUnavailable:
                    logger.exception("WebP conversion is unavailable - room type %s", category.pk)
                    error = _("Those pictures couldn't be processed. Try different ones.")

        return _photo_grid(request, {
            "photos": category.photos.on_the_form(),
            "remove_url_name": "villas:remove_room_photo",
            "villa": villa,
            "category": category,
            "error": error,
        })


class RoomPhotoDeleteView(ManagerRequiredMixin, View):
    """Takes a picture off the form. Nothing is really gone until Save."""

    def post(self, request, slug, pk, photo_pk):
        villa = _get_org_villa(request, slug)
        category = get_object_or_404(RoomCategory.objects.filter(villa=villa), pk=pk)
        _stage_removal(get_object_or_404(category.photos, pk=photo_pk), "room type", category.pk)
        return _photo_grid(request, {
            "photos": category.photos.on_the_form(),
            "remove_url_name": "villas:remove_room_photo",
            "villa": villa,
            "category": category,
        })


class VillaPhotoUploadView(ManagerRequiredMixin, View):
    """Pictures of the property itself, held aside until the page is saved.

    The file is written straight away but the row is marked pending, exactly
    as for a room type above - it becomes one of the villa's real pictures
    when Save is pressed, and is swept away if the page is simply left.

    Only reachable once a villa row exists - on the edit page, or when going
    back to step 1 on a draft. The very first time through step 1, before
    anything has been saved at all, photos are picked here go along with that
    first save instead - see VillaDetailsView.post.
    """

    def post(self, request, slug):
        villa = _get_org_villa(request, slug)
        files = request.FILES.getlist("photos")

        error = None
        if files:
            error = _check_photo_limits(files, _villa_photo_count(villa))
            if not error:
                try:
                    _store_photos(
                        request.organization, villa, _convert_photos(files),
                        VillaPhoto, "villa", pending=True,
                        crops=_parse_crops(request.POST, len(files)),
                    )
                except WebPUnavailable:
                    logger.exception("WebP conversion is unavailable - villa %s", villa.pk)
                    error = _("Those pictures couldn't be processed. Try different ones.")

        return _photo_grid(request, {
            "photos": villa.photos.on_the_form(),
            "remove_url_name": "villas:remove_villa_photo",
            "villa": villa,
            "error": error,
        })


class VillaPhotoDeleteView(ManagerRequiredMixin, View):
    """Takes a picture off the form. Nothing is really gone until Save."""

    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        _stage_removal(get_object_or_404(villa.photos, pk=pk), "villa", villa.pk)
        return _photo_grid(request, {
            "photos": villa.photos.on_the_form(),
            "remove_url_name": "villas:remove_villa_photo",
            "villa": villa,
        })


class PhotoCropView(ManagerRequiredMixin, View):
    """Moves the 16:9 frame on a picture that is already uploaded.

    Nothing is re-uploaded and nothing is cut out of the file: only the four
    numbers saying which part of the original the villa page should show move,
    so the same picture can be re-framed as many times as the operator likes
    without ever losing quality. The new display copies are built on the next
    guest request that asks for them - see webp_variant in images.py.

    Unlike adding or removing a picture, this is not held back until Save. It
    changes one picture's framing and nothing else on the page, and holding it
    would mean a second set of staged fields for very little.
    """

    photo_model = None
    owner_field = None
    remove_url_name = None

    def post(self, request, slug, pk=None, photo_pk=None):
        villa = _get_org_villa(request, slug)
        context = {"villa": villa, "remove_url_name": self.remove_url_name}

        if self.owner_field == "category":
            owner = get_object_or_404(RoomCategory.objects.filter(villa=villa), pk=pk)
            context["category"] = owner
        else:
            owner = villa

        photo = get_object_or_404(self.photo_model.objects.filter(**{self.owner_field: owner}), pk=photo_pk)
        box = _parse_crops(request.POST, 1)[0]
        photo.set_crop(box)
        photo.save(update_fields=["crop_x", "crop_y", "crop_width", "crop_height", "updated_at"])
        logger.info(
            "Re-framed photo %s on %s %s - box %s",
            photo.pk, self.owner_field, owner.pk, photo.crop,
        )

        context["photos"] = owner.photos.on_the_form()
        return _photo_grid(request, context)


class VillaPhotoCropView(PhotoCropView):
    photo_model = VillaPhoto
    owner_field = "villa"
    remove_url_name = "villas:remove_villa_photo"


class RoomPhotoCropView(PhotoCropView):
    photo_model = RoomCategoryPhoto
    owner_field = "category"
    remove_url_name = "villas:remove_room_photo"


# ---------------------------------------------------------------------------
# Amenities
# ---------------------------------------------------------------------------


class AmenityCreateView(ManagerRequiredMixin, View):
    """Adds something the built-in list doesn't cover.

    It is kept against the operator's own account, so it turns up as a
    ready-made tickbox on their next villa - and never on anyone else's.
    """

    def post(self, request):
        organization = request.organization
        # Which block asked for it, so the new tickbox joins that room type's
        # list and not one of the others on the page.
        category_pk = request.POST.get("category_pk", "")
        context = {
            "field_name": request.POST.get("field_name", f"{ROOMS_PREFIX}-0-amenities"),
            "category_pk": category_pk,
        }
        # Every room block on the page is inside one form, and HTMX sends that
        # whole form - so each block's box carries a name of its own and we
        # pick out the one belonging to the block that asked.
        typed = request.POST.get(f"new_amenity_{category_pk}", "")
        form = CustomAmenityForm({"name_en": typed}, organization=organization)

        if not form.is_valid():
            context["error"] = next(iter(form.errors.values()))[0]
            return render(request, "villas/_amenity_new.html", context)

        context["amenity"] = form.save()
        return render(request, "villas/_amenity_new.html", context)


class AmenityDeleteView(ManagerRequiredMixin, View):
    """Drops one of the operator's own custom amenities from their list.

    Scoped to `organization` so an operator can never touch another
    operator's amenity - and can never delete one of the shared, built-in
    ones, since those have no organization to match.
    """

    def post(self, request, pk):
        amenity = get_object_or_404(Amenity, pk=pk, organization=request.organization)
        amenity.delete()
        logger.info("Removed custom amenity %s for organization %s", pk, request.organization.pk)
        return HttpResponse("")


# ---------------------------------------------------------------------------
# "Things to do nearby" (feature #8)
# ---------------------------------------------------------------------------


class VillaActivitiesView(ManagerRequiredMixin, View):
    """Its own page, at villas/<slug>/activities/, listing this villa's local
    activities and letting the client add a new one. Only reachable once the
    villa is real and not a draft - Experience links to a villa through its
    own many-to-many, which needs a villa row to point at.
    """

    template_name = "villas/activities.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.villa = _get_org_villa(request, kwargs["slug"], drafts_too=False)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, slug):
        return self._render(getattr(self, "experience_form", None) or ExperienceForm())

    def _render(self, experience_form):
        return render(self.request, self.template_name, {
            "villa": self.villa,
            "experiences": self.villa.experiences.all(),
            "experience_form": experience_form,
        })


class VillaWebsiteToggleView(ManagerRequiredMixin, View):
    """Turns the villa's public web page on or off, from the "I want to have
    my website" checkbox on the activities page.
    """

    def post(self, request, slug):
        villa = _get_org_villa(request, slug, drafts_too=False)
        want_website = bool(request.POST.get("want_website"))

        if want_website:
            missing = villa.website_missing_requirements()
            if missing:
                logger.info(
                    "Refused to turn on website for villa %s by user %s - missing: %s",
                    villa.pk, request.user.pk, missing,
                )
                messages.error(
                    request,
                    _("Add these first before turning the website on: %(items)s")
                    % {"items": "; ".join(missing)},
                )
                return redirect("marketing_admin:overview")

        villa.is_listed_publicly = want_website
        villa.save(update_fields=["is_listed_publicly"])
        logger.info(
            "Set is_listed_publicly=%s for villa %s by user %s",
            villa.is_listed_publicly, villa.pk, request.user.pk,
        )
        if villa.is_listed_publicly:
            messages.success(request, _("Your villa's website is now on."))
        else:
            messages.success(request, _("Your villa's website is now off."))
        return redirect("marketing_admin:overview")


class VillaExperienceCreateView(ManagerRequiredMixin, View):
    """Adds a local activity straight to this villa's "Things to do nearby".

    `Experience` lives in apps.marketing and can be shared across villas
    through its own many-to-many - see ExperienceInline in
    apps.villas.admin - but an activity added from here is a fresh row of
    its own, linked only to this villa.
    """

    def post(self, request, slug):
        villa = _get_org_villa(request, slug, drafts_too=False)
        form = ExperienceForm(request.POST, request.FILES)
        if not form.is_valid():
            view = VillaActivitiesView()
            view.request, view.villa = request, villa
            return view._render(form)

        experience = form.save(commit=False)
        experience.organization = request.organization
        experience.save()
        experience.villas.add(villa)
        logger.info(
            "Added experience %s (%s) to villa %s by user %s",
            experience.pk, experience.name_en, villa.pk, request.user.pk,
        )
        messages.success(request, _('Added "%(name)s".') % {"name": experience.name_en})
        return redirect("villas:activities", slug=villa.slug)


class VillaExperienceUpdateView(ManagerRequiredMixin, View):
    """Editing one activity already on this villa's page. A standalone page
    rather than an inline card, so a photo swap gets the same clear
    save-or-cancel step as everything else that uploads a picture.
    """

    template_name = "villas/experience_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.villa = _get_org_villa(request, kwargs["slug"], drafts_too=False)
        self.experience = get_object_or_404(
            Experience, pk=kwargs["pk"], organization=request.organization, villas=self.villa,
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, slug, pk):
        return self._render(ExperienceForm(instance=self.experience))

    def post(self, request, slug, pk):
        form = ExperienceForm(request.POST, request.FILES, instance=self.experience)
        if not form.is_valid():
            return self._render(form)
        form.save()
        logger.info(
            "Updated experience %s (%s) on villa %s by user %s",
            self.experience.pk, self.experience.name_en, self.villa.pk, request.user.pk,
        )
        messages.success(request, _("Saved"))
        return redirect("villas:activities", slug=self.villa.slug)

    def _render(self, form):
        return render(self.request, self.template_name, {
            "form": form, "villa": self.villa, "experience": self.experience,
        })


class VillaExperienceDeleteView(ManagerRequiredMixin, View):
    """Takes an activity off this villa's page.

    Unlinked rather than blanket-deleted, since the same activity can be
    shared onto more than one villa - it is only actually deleted once no
    villa is showing it any more.
    """

    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug, drafts_too=False)
        experience = get_object_or_404(
            Experience, pk=pk, organization=request.organization, villas=villa,
        )
        experience.villas.remove(villa)
        name = experience.name_en
        left_on = experience.villas.count()
        if left_on == 0:
            experience.delete()
        logger.info(
            "Removed experience %s (%s) from villa %s by user %s - still on %s other villa(s)",
            pk, name, villa.pk, request.user.pk, left_on,
        )
        messages.success(request, _('Removed "%(name)s".') % {"name": name})
        return redirect("villas:activities", slug=villa.slug)


# ---------------------------------------------------------------------------
# Editing and removing a villa
# ---------------------------------------------------------------------------


class VillaUpdateView(VillaDetailsView):
    """Editing a villa's own details - step 1 of the same two-step form used
    to add one, since a villa is described the same way whichever door it
    came in by. Its rooms are step 2, at VillaRoomsView; the step indicator on
    each page links to the other one.
    """


class VillaDeleteView(ManagerRequiredMixin, DetailView):
    """Removing a villa here doesn't erase its history - bookings and
    documents point back at it, so this just marks it inactive, the same
    flag the picker already filters on. A confirmation page rather than a
    single-click action, since it takes a villa off the operator's active
    list.
    """

    model = Villa
    template_name = "villas/confirm_delete.html"
    context_object_name = "villa"
    slug_field = "slug"

    def get_queryset(self):
        org = self.request.organization
        return Villa.objects.filter(organization=org) if org else Villa.objects.none()

    def post(self, request, *args, **kwargs):
        villa = self.get_object()
        villa.is_active = False
        villa.save(update_fields=["is_active"])
        logger.info("Villa %s (%s) removed by user %s", villa.pk, villa.name, request.user.pk)
        messages.success(request, _("%(name)s was removed from your villas.") % {"name": villa.name})
        return redirect(safe_next(request, reverse_lazy("villas:list")))


# ---------------------------------------------------------------------------
# The calendar's inline room actions
# ---------------------------------------------------------------------------


class RoomQuickAddView(ManagerRequiredMixin, View):
    """One-click, no-form room add. No longer called from the calendar -
    "+ Add room" there now confirms then sends the operator to villas:add_room
    instead, since a room needs a real form (type, size, rate). Left in place
    rather than removed; nothing else in the UI calls this today.
    """

    def post(self, request, slug):
        villa = _get_org_villa(request, slug)
        add_rooms(villa, default_room_type(villa), 1)
        fallback = reverse("villas:edit", kwargs={"slug": villa.slug})
        return redirect(safe_next(request, fallback))


class RoomAddView(ManagerRequiredMixin, View):
    """The calendar's "+ Add room" button.

    A villa with only one room type has nothing to ask - the new room goes
    under that type. One with several needs to know which type first, so the
    card in _calendar_panel.html shows them and posts back here with
    category_id set; a missing or stale one (the type was removed while the
    card was open) is treated as "ask again" rather than guessing.
    """

    def post(self, request, slug):
        villa = _get_org_villa(request, slug)
        fallback = reverse("villas:edit", kwargs={"slug": villa.slug})
        next_url = safe_next(request, fallback)

        categories = list(villa.room_categories.all())
        if len(categories) <= 1:
            category = categories[0] if categories else default_room_type(villa)
        else:
            category_id = request.POST.get("category_id")
            category = next((c for c in categories if str(c.pk) == category_id), None)
            if category is None:
                messages.error(request, _("Pick a room type first."))
                return redirect(next_url)

        add_rooms(villa, category, 1)
        return redirect(next_url)


class RoomDeleteView(ManagerRequiredMixin, View):
    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        room = get_object_or_404(Room.objects.filter(villa=villa), pk=pk)
        fallback = reverse("villas:edit", kwargs={"slug": villa.slug})
        next_url = safe_next(request, fallback)

        if villa.rooms.filter(is_active=True).count() <= 1:
            messages.error(request, _("A villa needs at least one room - add another before removing this one."))
            return redirect(next_url)

        try:
            room.delete()
        except ProtectedError:
            messages.error(request, _("This room still has bookings - move or remove those first."))
        return redirect(next_url)


class VillaRenameView(ManagerRequiredMixin, View):
    """Inline rename from the calendar row: commits on change, no save
    button, per the design handoff's inline-editing behavior. Blank names
    are ignored rather than saved, since there's no separate validation step.
    """

    def post(self, request, slug):
        villa = _get_org_villa(request, slug)
        name = request.POST.get("name", "").strip()
        if name:
            villa.name = name
            villa.save(update_fields=["name"])
        return HttpResponse(status=204)


class RoomRenameView(ManagerRequiredMixin, View):
    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        room = get_object_or_404(Room.objects.filter(villa=villa), pk=pk)
        name = request.POST.get("name", "").strip()[:10]
        if name:
            room.name = name
            room.save(update_fields=["name"])
        return HttpResponse(status=204)

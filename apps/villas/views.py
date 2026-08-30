"""The villa picker, and the two-step form behind "add a villa".

Why two steps and a draft row: step 1 is about the property, step 2 is about
its rooms, and the two ask for genuinely different things. Rather than hold
step 1 in the session, finishing it saves a real villa marked `is_draft`. That
buys two things - the operator can close the browser and come back to it, and
each room type on step 2 is already a real row, so a photo has somewhere to go
the moment it is picked. A draft is invisible everywhere else in the app and
does not use up a villa slot on the operator's plan: see VillaQuerySet.live().
"""

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

from apps.bookings.models import Booking
from apps.core.utils import safe_next
from apps.villas.forms import (
    BALI_AREAS,
    CustomAmenityForm,
    RoomCategoryFormSet,
    VillaForm,
)
from apps.villas.images import WebPUnavailable, to_webp
from apps.villas.models import (
    DEFAULT_ROOM_TYPE,
    MAX_ROOMS_PER_TYPE,
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
        villas = list(
            org.villas.live()
            .annotate(room_count=Count("rooms", filter=Q(rooms__is_active=True)))
            .prefetch_related("room_categories")
            .order_by("name")
        )

        # A villa has several rooms, so it's "available" again as soon as its
        # earliest-checking-out current booking frees up a room - not when
        # every room is empty. Picking the earliest check-out per villa also
        # covers the (should-never-happen, but possible via manual admin
        # edits) case of overlapping bookings.
        available_from = {}
        current_bookings = Booking.objects.filter(
            organization=org,
            villa_id__in=[v.id for v in villas],
            check_in__lte=today, check_out__gt=today,
            status__in=OCCUPYING_STATUSES,
        ).values_list("villa_id", "check_out")
        for villa_id, check_out in current_bookings:
            if villa_id not in available_from or check_out < available_from[villa_id]:
                available_from[villa_id] = check_out

        for villa in villas:
            villa.available_from = available_from.get(villa.id)  # None = available now

        context.update(
            villas=villas,
            # Villas somebody started adding and never finished. Shown here so
            # an unfinished one can be picked up again instead of sitting
            # invisible in the database forever.
            drafts=list(org.villas.filter(is_draft=True, is_active=True).order_by("-updated_at")),
            can_add_villa=org.can_add_villa,
            villa_limit=org.villa_limit,
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


def _convert_photos(files):
    """Turn what was uploaded into WebP, before anything at all is written.

    Done first, and separately from storing it, so a picture that can't be
    converted stops the whole thing while there is still nothing to undo.
    Per CLAUDE.md a failed conversion is never papered over with a JPEG - this
    raises WebPUnavailable and the caller says so plainly instead.
    """
    return [to_webp(uploaded) for uploaded in files]


def _store_photos(organization, owner, webp_files, photo_model, owner_field):
    """File already-converted pictures against a villa or a room type."""
    start = photo_model.objects.filter(**{owner_field: owner}).count()
    saved = [
        photo_model.objects.create(
            organization=organization, image=webp, sort_order=start + offset,
            is_cover=(start + offset == 0), **{owner_field: owner},
        )
        for offset, webp in enumerate(webp_files)
    ]
    if saved:
        logger.info(
            "Stored %s photo(s) as WebP for %s %s", len(saved), owner_field, owner.pk,
        )
    return saved


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


class VillaDetailsView(LoginRequiredMixin, View):
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
        return self._render(VillaForm(instance=self.villa))

    def post(self, request, slug=None):
        form = VillaForm(request.POST, instance=self.villa)
        if not form.is_valid():
            return self._render(form)

        # Converted before a single row is written, so a picture that can't be
        # turned into WebP stops this while there is still nothing to undo.
        try:
            webp_photos = _convert_photos(request.FILES.getlist("photos"))
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

            if not villa.room_categories.exists():
                create_room_type(villa, DEFAULT_ROOM_TYPE, how_many=1)
            if webp_photos:
                _store_photos(self.organization, villa, webp_photos, VillaPhoto, "villa")

        logger.info(
            "Villa %s (%s) saved at step 1 by user %s - draft=%s",
            villa.pk, villa.name, request.user.pk, villa.is_draft,
        )
        if villa.is_draft:
            return redirect("villas:rooms", slug=villa.slug)
        messages.success(request, _("Saved."))
        return redirect("villas:edit", slug=villa.slug)

    def _render(self, form):
        return render(self.request, self.template_name, {
            "form": form,
            "villa": self.villa,
            "organization": self.organization,
            "areas": BALI_AREAS,
            "step": 1,
        })


# ---------------------------------------------------------------------------
# Adding a villa - step 2, the rooms
# ---------------------------------------------------------------------------


class VillaRoomsView(LoginRequiredMixin, View):
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
        messages.success(request, _("Saved."))
        return redirect("villas:edit", slug=self.villa.slug)

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


class RoomCategoryCreateView(LoginRequiredMixin, RoomBlocksPartialMixin, View):
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


class RoomCategoryDeleteView(LoginRequiredMixin, RoomBlocksPartialMixin, View):
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


class RoomPhotoUploadView(LoginRequiredMixin, View):
    """Pictures of one kind of room, saved the moment they are picked.

    They can go straight to storage because the block they belong to is
    already a real room type - which is the whole reason step 1 saves a draft
    instead of holding everything in memory.
    """

    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        category = get_object_or_404(RoomCategory.objects.filter(villa=villa), pk=pk)
        files = request.FILES.getlist("photos")

        error = None
        if files:
            try:
                _store_photos(
                    request.organization, category, _convert_photos(files),
                    RoomCategoryPhoto, "category",
                )
            except WebPUnavailable:
                logger.exception("WebP conversion is unavailable - room type %s", category.pk)
                error = _("Those pictures couldn't be processed. Try different ones.")

        return render(request, "villas/_photo_grid.html", {
            "photos": category.photos.all(),
            "remove_url_name": "villas:remove_room_photo",
            "villa": villa,
            "category": category,
            "error": error,
        })


class RoomPhotoDeleteView(LoginRequiredMixin, View):
    def post(self, request, slug, pk, photo_pk):
        villa = _get_org_villa(request, slug)
        category = get_object_or_404(RoomCategory.objects.filter(villa=villa), pk=pk)
        get_object_or_404(category.photos, pk=photo_pk).delete()
        logger.info("Removed photo %s from room type %s", photo_pk, category.pk)
        return render(request, "villas/_photo_grid.html", {
            "photos": category.photos.all(),
            "remove_url_name": "villas:remove_room_photo",
            "villa": villa,
            "category": category,
        })


class VillaPhotoUploadView(LoginRequiredMixin, View):
    """Pictures of the property itself, saved the moment they are picked.

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
            try:
                _store_photos(request.organization, villa, _convert_photos(files), VillaPhoto, "villa")
            except WebPUnavailable:
                logger.exception("WebP conversion is unavailable - villa %s", villa.pk)
                error = _("Those pictures couldn't be processed. Try different ones.")

        return render(request, "villas/_photo_grid.html", {
            "photos": villa.photos.all(),
            "remove_url_name": "villas:remove_villa_photo",
            "villa": villa,
            "error": error,
        })


class VillaPhotoDeleteView(LoginRequiredMixin, View):
    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        get_object_or_404(villa.photos, pk=pk).delete()
        logger.info("Removed photo %s from villa %s", pk, villa.pk)
        return render(request, "villas/_photo_grid.html", {
            "photos": villa.photos.all(),
            "remove_url_name": "villas:remove_villa_photo",
            "villa": villa,
        })


# ---------------------------------------------------------------------------
# Amenities
# ---------------------------------------------------------------------------


class AmenityCreateView(LoginRequiredMixin, View):
    """Adds something the built-in list doesn't cover.

    It is kept against the operator's own account, so it turns up as a
    ready-made tickbox on their next villa - and never on anyone else's.
    """

    def post(self, request):
        organization = request.organization
        form = CustomAmenityForm(request.POST, organization=organization)
        # Which block asked for it, so the new tickbox joins that room type's
        # list and not one of the others on the page.
        context = {
            "field_name": request.POST.get("field_name", f"{ROOMS_PREFIX}-0-amenities"),
            "category_pk": request.POST.get("category_pk", ""),
        }

        if not form.is_valid():
            context["error"] = next(iter(form.errors.values()))[0]
            return render(request, "villas/_amenity_new.html", context)

        context["amenity"] = form.save()
        return render(request, "villas/_amenity_new.html", context)


# ---------------------------------------------------------------------------
# Editing and removing a villa
# ---------------------------------------------------------------------------


class VillaUpdateView(VillaDetailsView):
    """Editing a villa's own details - step 1 of the same two-step form used
    to add one, since a villa is described the same way whichever door it
    came in by. Its rooms are step 2, at VillaRoomsView; the step indicator on
    each page links to the other one.
    """


class VillaDeleteView(LoginRequiredMixin, DetailView):
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


class RoomQuickAddView(LoginRequiredMixin, View):
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


class RoomAddView(LoginRequiredMixin, View):
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


class RoomDeleteView(LoginRequiredMixin, View):
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


class VillaRenameView(LoginRequiredMixin, View):
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


class RoomRenameView(LoginRequiredMixin, View):
    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        room = get_object_or_404(Room.objects.filter(villa=villa), pk=pk)
        name = request.POST.get("name", "").strip()
        if name:
            room.name = name
            room.save(update_fields=["name"])
        return HttpResponse(status=204)

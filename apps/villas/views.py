"""Villa picker - the first screen after logging in.

Matches how most multi-property tools (Little Hotelier, Cloudbeds, Guesty)
work: pick which property you're working on before doing anything else.

Selecting a villa here does not yet filter the rest of the app - the owner
dashboard and other screens still show every villa in the operator's
portfolio. That scoping is real future work, not shipped with this page.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView, View

from apps.bookings.models import Booking
from apps.villas.forms import (
    RoomCategoryForm,
    VillaForm,
    parse_room_types,
    submitted_room_type_rows,
)
from apps.villas.images import WebPUnavailable, to_webp
from apps.villas.models import (
    MAX_ROOMS_PER_TYPE,
    Room,
    RoomCategory,
    Villa,
    VillaPhoto,
    add_rooms,
    create_room_type,
    default_room_type,
    set_room_count,
)

OCCUPYING_STATUSES = [Booking.Status.CONFIRMED, Booking.Status.BLOCKED]


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
            org.villas.filter(is_active=True)
            .annotate(room_count=Count("rooms", filter=Q(rooms__is_active=True)))
            .order_by("name")
        )

        # A villa currently occupied is "available" again the day its current
        # booking checks out - not some vague "occupied" flag. Picking the
        # latest check-out per villa covers the (should-never-happen, but
        # possible via manual admin edits) case of overlapping bookings.
        available_from = {}
        current_bookings = Booking.objects.filter(
            organization=org,
            villa_id__in=[v.id for v in villas],
            check_in__lte=today, check_out__gt=today,
            status__in=OCCUPYING_STATUSES,
        ).values_list("villa_id", "check_out")
        for villa_id, check_out in current_bookings:
            if villa_id not in available_from or check_out > available_from[villa_id]:
                available_from[villa_id] = check_out

        for villa in villas:
            villa.available_from = available_from.get(villa.id)  # None = available now

        context.update(
            villas=villas,
            can_add_villa=org.can_add_villa,
            villa_limit=org.villa_limit,
        )
        return context


class VillaCreateView(LoginRequiredMixin, CreateView):
    model = Villa
    form_class = VillaForm
    template_name = "villas/add.html"
    success_url = reverse_lazy("villas:list")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)  # let LoginRequiredMixin handle it

        org = request.organization
        if org is None:
            return redirect("villas:list")  # shows the "no organization" state there

        # Checked here so a direct POST can't bypass a disabled button - the
        # button being hidden is a courtesy, not the actual enforcement.
        if not org.can_add_villa:
            messages.error(
                request,
                _("You've reached your plan's limit of %(limit)s villas. Contact us to add more.")
                % {"limit": org.villa_limit},
            )
            return redirect("villas:list")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.request.organization
        # Re-rendered after an error with whatever was typed, so nobody has to
        # retype their room types; a fresh form starts with one empty row.
        rows = submitted_room_type_rows(self.request.POST) if self.request.method == "POST" else []
        context["room_type_rows"] = rows or [{"name": "", "count": 1}]
        context["max_rooms_per_type"] = MAX_ROOMS_PER_TYPE
        return context

    def get_success_url(self):
        # The calendar's "+ Add villa" link carries ?next= so creating a
        # villa from there returns you to the calendar, not the villa list.
        next_url = self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={self.request.get_host()}):
            return next_url
        return str(self.success_url)

    def form_valid(self, form):
        org = self.request.organization

        # Checked before anything is written, for the same reason as the photo
        # below: a villa with no rooms has nothing to draw on the calendar, so
        # it must never be saved half-built.
        room_types, room_type_errors = parse_room_types(self.request.POST)
        if room_type_errors:
            for message in room_type_errors:
                form.add_error(None, message)
            return self.form_invalid(form)

        # Converted before anything is written: a photo is mandatory, so a
        # villa must never end up saved without one. Per CLAUDE.md, a failed
        # WebP conversion is never silently papered over with a JPEG/PNG
        # fallback - the whole submission fails instead, with an honest
        # message, rather than quietly breaking the "at least one photo" rule.
        try:
            webp_file = to_webp(form.cleaned_data["cover_photo"])
        except WebPUnavailable:
            form.add_error(
                None,
                _("The photo couldn't be processed. Try a different image, or add the villa from admin instead."),
            )
            return self.form_invalid(form)

        form.instance.organization = org
        form.instance.slug = self._unique_slug(org, form.instance.name)
        # The room types typed on this form are created just below, in the
        # same transaction, so the villa must not also be given the starter
        # room every other route gets. See new_villas_start_with_rooms.
        form.instance.skip_default_rooms = True

        with transaction.atomic():
            response = super().form_valid(form)  # saves self.object
            for room_type in room_types:
                create_room_type(self.object, room_type.name, room_type.count)
            self.object.amenities.set(form.cleaned_data["amenities"])
            VillaPhoto.objects.create(
                organization=org, villa=self.object, image=webp_file, is_cover=True,
            )
        return response

    @staticmethod
    def _unique_slug(org, name: str) -> str:
        base = slugify(name)
        slug = base
        suffix = 2
        while org.villas.filter(slug=slug).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug


class VillaUpdateView(LoginRequiredMixin, UpdateView):
    model = Villa
    form_class = VillaForm
    template_name = "villas/edit.html"
    success_url = reverse_lazy("villas:list")
    slug_field = "slug"

    def get_queryset(self):
        org = self.request.organization
        return Villa.objects.filter(organization=org) if org else Villa.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.request.organization
        context["room_category_form"] = RoomCategoryForm(villa=self.object)
        context["room_groups"] = [
            {"category": category, "rooms": list(category.rooms.order_by("id"))}
            for category in self.object.room_categories.prefetch_related("rooms")
        ]
        # Only reachable on older data - removing a room type now moves its
        # rooms to another one rather than leaving them behind. Shown anyway,
        # so a room can never quietly disappear from this panel.
        context["untyped_rooms"] = list(self.object.rooms.filter(category__isnull=True).order_by("id"))
        context["max_rooms_per_type"] = MAX_ROOMS_PER_TYPE
        return context

    def form_valid(self, form):
        webp_file = None
        if form.cleaned_data.get("cover_photo"):
            try:
                webp_file = to_webp(form.cleaned_data["cover_photo"])
            except WebPUnavailable:
                form.add_error(
                    None,
                    _("The photo couldn't be processed. Try a different image, or leave it empty to keep the current one."),
                )
                return self.form_invalid(form)

        with transaction.atomic():
            response = super().form_valid(form)
            self.object.amenities.set(form.cleaned_data["amenities"])
            if webp_file is not None:
                self.object.photos.filter(is_cover=True).update(is_cover=False)
                VillaPhoto.objects.create(
                    organization=self.object.organization, villa=self.object,
                    image=webp_file, is_cover=True,
                )
        return response


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
        messages.success(request, _("%(name)s was removed from your villas.") % {"name": villa.name})
        return redirect(_safe_next(request, reverse_lazy("villas:list")))


def _get_org_villa(request, slug):
    org = request.organization
    return get_object_or_404(Villa.objects.filter(organization=org) if org else Villa.objects.none(), slug=slug)


def _safe_next(request, fallback_url):
    """POST['next'] if it's a same-site path, else the given fallback URL
    (an already-resolved path, not a URL name - callers that need kwargs,
    e.g. a villa slug, resolve those themselves before calling this).
    Used by the calendar's inline villa/room actions, which all need to
    return to wherever the calendar was (with its date range and search
    intact) rather than a fixed destination.
    """
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return fallback_url


class RoomQuickAddView(LoginRequiredMixin, View):
    """The calendar's "+ Add room" button - one click, no form. The new room
    goes under the villa's first room type and is named to follow that type's
    other rooms, so a villa's rooms read as one series however they were
    added. Anything more deliberate - a different type, a different name -
    belongs on the villa's own rooms panel.
    """

    def post(self, request, slug):
        villa = _get_org_villa(request, slug)
        add_rooms(villa, default_room_type(villa), 1)
        fallback = reverse_lazy("villas:edit", kwargs={"slug": villa.slug})
        return redirect(_safe_next(request, fallback))


class RoomDeleteView(LoginRequiredMixin, View):
    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        room = get_object_or_404(Room.objects.filter(villa=villa), pk=pk)
        fallback = reverse_lazy("villas:edit", kwargs={"slug": villa.slug})
        next_url = _safe_next(request, fallback)

        if villa.rooms.filter(is_active=True).count() <= 1:
            messages.error(request, _("A villa needs at least one room - add another before removing this one."))
            return redirect(next_url)

        try:
            room.delete()
        except ProtectedError:
            messages.error(request, _("This room still has bookings - move or remove those first."))
        return redirect(next_url)


class RoomCategoryCreateView(LoginRequiredMixin, View):
    """Add a room type to one villa, along with that many rooms."""

    def post(self, request, slug):
        villa = _get_org_villa(request, slug)
        form = RoomCategoryForm(request.POST, villa=villa)
        if form.is_valid():
            create_room_type(villa, form.cleaned_data["name"], form.cleaned_data["count"])
        else:
            messages.error(request, next(iter(form.errors.values()))[0])
        return redirect("villas:edit", slug=villa.slug)


class RoomCategoryUpdateView(LoginRequiredMixin, View):
    """One Save for a whole room type: what it's called, how many rooms it
    has, and what each of those rooms is called.

    Renames are applied before the count changes, so rooms added in the same
    save follow the names as they now are, not as they were.
    """

    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        category = get_object_or_404(RoomCategory.objects.filter(villa=villa), pk=pk)
        redirect_to = redirect("villas:edit", slug=villa.slug)

        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, _("Give the room type a name."))
            return redirect_to
        if villa.room_categories.filter(name__iexact=name).exclude(pk=category.pk).exists():
            messages.error(request, _("This villa already has a room type with that name."))
            return redirect_to
        if name != category.name:
            category.name = name
            category.save(update_fields=["name"])

        rooms = list(category.rooms.order_by("id"))
        for room in rooms:
            new_name = request.POST.get(f"room_name_{room.pk}", "").strip()
            if new_name and new_name != room.name:
                room.name = new_name
                room.save(update_fields=["name"])

        # 0 is allowed here, unlike when adding a type: a villa can keep a
        # type it isn't using at the moment without deleting the label.
        try:
            count = int(request.POST.get("count", "").strip())
        except ValueError:
            count = -1
        if count < 0 or count > MAX_ROOMS_PER_TYPE:
            messages.error(
                request,
                _("Say how many rooms of this type there are, from 0 to %(most)s.")
                % {"most": MAX_ROOMS_PER_TYPE},
            )
            return redirect_to

        added, removed = set_room_count(villa, category, count)
        kept = (len(rooms) - count) - removed
        if kept > 0:
            # Honest rather than silent: a room with bookings on it stays, and
            # the number on screen has to say so instead of pretending.
            messages.error(
                request,
                _("%(count)s room(s) were kept because they still have bookings on them.")
                % {"count": kept},
            )
        elif added or removed:
            messages.success(
                request,
                _("%(name)s now has %(count)s room(s).") % {"name": category.name, "count": count},
            )
        return redirect_to


class RoomCategoryDeleteView(LoginRequiredMixin, View):
    """Remove a room type. Its rooms move to another one of the villa's types
    rather than being deleted - a room can hold real bookings, so tidying up a
    label must never take those off the calendar. A villa's only room type
    can't be removed while rooms are still filed under it, since they would
    have nowhere to go.
    """

    def post(self, request, slug, pk):
        villa = _get_org_villa(request, slug)
        category = get_object_or_404(RoomCategory.objects.filter(villa=villa), pk=pk)
        in_use = category.rooms.count()
        moved_to = villa.room_categories.exclude(pk=category.pk).first()

        if in_use and moved_to is None:
            messages.error(
                request,
                _("Add another room type first - this villa's rooms need one to belong to."),
            )
            return redirect("villas:edit", slug=villa.slug)

        if in_use:
            category.rooms.update(category=moved_to)
            messages.success(
                request,
                _("Room type removed. %(count)s room(s) moved to %(name)s.")
                % {"count": in_use, "name": moved_to.name},
            )
        category.delete()
        return redirect("villas:edit", slug=villa.slug)


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

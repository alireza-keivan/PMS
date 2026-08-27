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
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from apps.bookings.models import Booking
from apps.villas.forms import VillaForm
from apps.villas.images import WebPUnavailable, to_webp
from apps.villas.models import Villa, VillaPhoto

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
        villas = list(org.villas.filter(is_active=True).order_by("name"))

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
        return context

    def form_valid(self, form):
        org = self.request.organization

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

        with transaction.atomic():
            response = super().form_valid(form)  # saves self.object
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
        return redirect("villas:list")

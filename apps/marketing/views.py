"""The public villa pages, at /villa/<org>/<villa>/.

Kept in its own module so that "is this view public?" is answered by the
filename, the same way apps.guests.portal_views is. Four rules hold for
everything in here, without exception:

  1. No LoginRequiredMixin and no request.organization. The visitor has no
     account, so OrganizationMiddleware leaves that None - which means the
     usual tenant scoping does not fire at all. Every lookup therefore names
     the organization explicitly, through the org slug in the URL. See
     published_villa_or_404.

  2. Published means published. One definition, in VillaQuerySet.public(),
     and anything failing it is a 404 - not a redirect, not a thinner page.

  3. The template gets plain dictionaries, never a model instance. A public
     page handed a Villa can walk `villa.bookings`, `villa.organization`,
     `booking.guest` - one careless template line away from showing another
     operator's guests. So the view reads the handful of fields the page
     needs and passes those, and nothing on the page can reach any further.
     The street address is not among them: the area is public, the address
     is not until someone has actually booked.

  4. Nothing here writes to live booking or availability data.
"""

import logging

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, View

from apps.marketing.forms import BookingEnquiryForm
from apps.marketing.models import Experience
from apps.villas.images import responsive_srcset, webp_variant
from apps.villas.models import RoomCategory, Villa, VillaPhoto

logger = logging.getLogger(__name__)

# How many amenities the grid shows before the rest are folded away. Matches
# the design; the fold itself is a <details>, so it costs no JavaScript.
AMENITIES_BEFORE_FOLD = 8


def published_villa_or_404(org_slug: str, villa_slug: str) -> Villa:
    """The villa at this address, or nothing at all.

    Both slugs are matched together, so a villa is only ever reachable under
    its own operator's slug: asking for /villa/ubud/melati/ when Melati
    belongs to Canggu is a 404, not somebody else's villa page. This is the
    whole of the tenant check on the public side - there is no logged-in user
    to scope by - which is why it lives in one function that every public view
    goes through.
    """
    try:
        return (
            Villa.objects.public()
            .select_related("organization")
            .get(organization__slug=org_slug, slug=villa_slug)
        )
    except Villa.DoesNotExist:
        # Logged at info, not warning: a stale link or a guessed URL is
        # ordinary. What matters is being able to answer "why did my villa
        # page 404?" - and the answer is almost always that it is not listed.
        logger.info("Public villa page missed: org=%s villa=%s", org_slug, villa_slug)
        raise Http404("No published villa here.") from None


def rupiah(amount) -> str:
    """1500000 -> "Rp 1.500.000". Never a bare number: an unlabelled figure
    invites being read in the wrong currency (same rule as
    apps.guests.views._format_money and apps.bookings.services._money).

    Dots, always - not the active locale's separator. This is a price in
    rupiah written on a Bali villa's page, and it is written the way it is
    written in Bali whichever language the visitor is reading. Letting the
    English locale group it with commas would print "Rp 2,500,000", which an
    Indonesian reader can reasonably misread by a factor of a thousand.
    """
    if not amount:
        return ""
    return f"Rp {int(amount):,}".replace(",", ".")


def in_language(obj, base: str) -> str:
    """The `_id` field when the page is in Indonesian, else the `_en` one.

    Falls back to English when the Indonesian translation is simply not filled
    in - an operator who has only written one description should still have a
    page, not a blank section.
    """
    if translation.get_language() == "id":
        value = (getattr(obj, f"{base}_id", "") or "").strip()
        if value:
            return value
    return (getattr(obj, f"{base}_en", "") or "").strip()


def _photo_dict(photo, sizes: str) -> dict:
    """One picture, as the three things the template needs and nothing else."""
    return {
        "url": webp_variant(photo.image, 960),
        "srcset": responsive_srcset(photo.image),
        "sizes": sizes,
        "caption": in_language(photo, "caption"),
    }


def _live_photos(queryset):
    """Pictures the villa really has right now.

    Both staging flags are excluded, not just `is_pending`: a picture the
    operator has taken off the form but not yet saved is still live for the
    staff screens (see PhotoQuerySet.live), but showing it on the open web is
    the one place that guess goes the wrong way.
    """
    return queryset.filter(is_pending=False, pending_delete=False).order_by("sort_order", "id")


def _villa_photos(villa) -> tuple:
    """(cover, gallery). The cover is the one flagged as such, or failing that
    simply the first - a villa whose operator never picked one still gets a
    hero image rather than a hole where it should be.
    """
    photos = list(_live_photos(VillaPhoto.objects.filter(villa=villa)))
    if not photos:
        return None, []
    cover = next((p for p in photos if p.is_cover), photos[0])
    gallery = [p for p in photos if p.pk != cover.pk]
    return (
        _photo_dict(cover, "(min-width: 1024px) 1100px, 100vw"),
        [_photo_dict(p, "(min-width: 1024px) 320px, 80vw") for p in gallery],
    )


def _room_types(villa) -> list:
    """The villa's room types, each with its own photo, price and amenities."""
    categories = list(
        RoomCategory.objects.filter(villa=villa)
        .prefetch_related("amenities", "photos")
        .order_by("sort_order", "name")
    )
    rooms = []
    for category in categories:
        # display_photos already honours use_first_category_photos - a room
        # type borrowing the first one's pictures is decided on the model, not
        # re-decided here.
        photos = _live_photos(category.display_photos)
        first = photos.first()
        rooms.append({
            "id": category.pk,
            "name": category.name,
            "size_sqm": category.size_sqm,
            "max_guests": category.max_guests,
            "minimum_nights": category.minimum_nights,
            "nightly_rate": rupiah(category.nightly_rate),
            "amenities": [in_language(a, "name") for a in category.amenities.all()],
            "photo": _photo_dict(first, "(min-width: 1024px) 220px, 90vw") if first else None,
        })
    return rooms


def _villa_amenities(villa) -> list:
    """Everything the property offers, gathered from its room types.

    Amenities are recorded per room type, but a guest reading the page wants
    to know what the villa has - so they are pooled and de-duplicated, in the
    language of the page. Each one carries its icon key (blank for anything
    an operator typed in themselves) so the template can show a matching mark.
    """
    by_name = {}
    for category in villa.room_categories.prefetch_related("amenities"):
        for amenity in category.amenities.all():
            name = in_language(amenity, "name")
            if name:
                by_name[name] = amenity.icon
    return [{"name": name, "icon": by_name[name]} for name in sorted(by_name)]


def _experiences(villa) -> list:
    """Things to do nearby (feature #8). Absent entirely if there are none."""
    rows = Experience.objects.filter(villas=villa, is_active=True, organization=villa.organization_id)
    out = []
    for experience in rows:
        out.append({
            "name": in_language(experience, "name"),
            "description": in_language(experience, "description"),
            "photo_url": experience.photo.url if experience.photo else None,
        })
    return out


def _shortest_stay(villa) -> int:
    """The fewest nights anyone can book, across the villa's room types."""
    minimums = [c.minimum_nights for c in villa.room_categories.all() if c.minimum_nights]
    return min(minimums) if minimums else 1


def _single_price(rooms: list) -> str | None:
    """The nightly rate to show without waiting for a room to be picked -
    only when it's true for every room type, so it never implies a rate that
    isn't actually available on some of them.
    """
    if not rooms:
        return None
    rates = {r["nightly_rate"] for r in rooms}
    if len(rates) == 1:
        return next(iter(rates)) or None
    return None


def page_context(request, villa, form=None, **extra) -> dict:
    """Everything the page renders, as plain values.

    Note what is not in here: no Villa instance, no Organization instance, no
    queryset the template could iterate into something private.
    """
    cover, gallery = _villa_photos(villa)
    rooms = _room_types(villa)
    page_url = request.build_absolute_uri(
        reverse("marketing:villa_page", kwargs={"org": villa.organization.slug, "villa": villa.slug})
    )

    description = in_language(villa, "description")
    context = {
        "villa_name": villa.name,
        "area": villa.area,
        "property_type": villa.get_property_type_display(),
        "bedrooms": villa.bedrooms,
        "sleeps": villa.sleeps,
        "description": description,
        # A one-line version for the <meta> tags and the WhatsApp preview.
        "summary": (description[:157] + "...") if len(description) > 160 else description,
        "check_in_time": villa.check_in_time,
        "check_out_time": villa.check_out_time,
        "google_maps_url": villa.google_maps_url,
        "google_maps_embed_url": villa.google_maps_embed_url,
        "operator_name": villa.organization.name,
        "whatsapp_number": villa.organization.whatsapp_number,

        "cover": cover,
        "gallery": gallery,
        "rooms": rooms,
        "amenities": _villa_amenities(villa),
        "amenities_fold_at": AMENITIES_BEFORE_FOLD,
        "experiences": _experiences(villa),

        "shortest_stay": _shortest_stay(villa),
        # For the booking panel: no price is shown there until a room is
        # chosen (CLAUDE.md rule 2 - "from Rp X" up front implies every room
        # is that price, which isn't true once there's more than one type).
        # Keyed by room id as a string since that's how Alpine reads it off
        # the <select>'s value.
        "room_prices": {str(r["id"]): r["nightly_rate"] for r in rooms},
        # The one exception: if every room type costs the same (or there's
        # only one to begin with), that price isn't misleading - show it
        # right away, in the panel and the phone bar.
        "single_price": _single_price(rooms),

        "page_url": page_url,
        "book_url": reverse(
            "marketing:book", kwargs={"org": villa.organization.slug, "villa": villa.slug}
        ),
        "form": form if form is not None else BookingEnquiryForm(villa=villa),
    }
    context.update(extra)
    return context


class VillaPageView(TemplateView):
    """The villa's own page. One template, phone layout first, desktop through
    Tailwind's breakpoints - never two templates chosen by sniffing a device.
    """

    template_name = "public/villa_page.html"

    def get(self, request, *args, **kwargs):
        villa = published_villa_or_404(kwargs["org"], kwargs["villa"])
        logger.info(
            "Public villa page viewed: villa %s (%s) of org %s, language %s",
            villa.pk, villa.slug, villa.organization.slug, translation.get_language(),
        )
        return render(request, self.template_name, page_context(request, villa))


class DirectBookingView(View):
    """Someone asked to stay.

    Records the request and tells them it has been received - nothing more.
    No payment, and nothing written to live booking or availability data:
    the dates are only *read* to answer honestly whether they are free. The
    wording on the way out says the owner will get back to them, because
    that is what actually happens - nobody has been messaged yet (the
    WhatsApp hand-off is build order step 3 and has no provider behind it).
    """

    def get(self, request, *args, **kwargs):
        # Somebody reloaded the POST address or typed it in directly.
        villa = published_villa_or_404(kwargs["org"], kwargs["villa"])
        return render(request, "public/villa_page.html", page_context(request, villa))

    def post(self, request, *args, **kwargs):
        villa = published_villa_or_404(kwargs["org"], kwargs["villa"])
        form = BookingEnquiryForm(request.POST, villa=villa)

        logger.info(
            "Booking attempt on villa %s (%s): %s to %s for %s guest(s)",
            villa.pk, villa.slug,
            request.POST.get("check_in"), request.POST.get("check_out"),
            request.POST.get("guest_count"),
        )

        if not form.is_valid():
            logger.info(
                "Booking refused on villa %s: %s | field errors: %s",
                villa.pk,
                form.rejection or "failed validation",
                form.errors.as_json(),
            )
            return render(
                request, "public/villa_page.html",
                page_context(request, villa, form=form), status=400,
            )

        enquiry = form.save(commit=False)
        # Set from the villa, never from anything the visitor posted - this is
        # the row's tenant, and it is not the visitor's to choose.
        enquiry.organization = villa.organization
        enquiry.villa = villa
        category = form.available_category
        if category and category.nightly_rate:
            enquiry.quoted_total = category.nightly_rate * enquiry.nights
        enquiry.save()

        logger.info(
            "Booking enquiry %s recorded: villa %s, room type %s, %s to %s, %s guest(s)",
            enquiry.pk, villa.pk, enquiry.room_category_id,
            enquiry.check_in, enquiry.check_out, enquiry.guest_count,
        )

        return render(
            request, "public/villa_page.html",
            page_context(
                request, villa,
                sent=True,
                sent_message=_("Thanks - the owner has your request and will get back to you."),
            ),
        )

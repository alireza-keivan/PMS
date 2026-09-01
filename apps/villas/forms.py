"""The forms behind the two-step "add a villa" page, and the edit page.

Step 1 (VillaForm) is about the property as a whole. Step 2 is a formset of
RoomCategoryForm - one block per kind of room - and that is where every number
describing a room lives: how big, how many guests, what it costs, the fewest
nights it can be booked for.
"""

import logging
import re

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.villas.models import (
    DEFAULT_CHECK_IN_TIME,
    DEFAULT_CHECK_OUT_TIME,
    MAX_ROOMS_PER_TYPE,
    Amenity,
    RoomCategory,
    Villa,
)

logger = logging.getLogger(__name__)

# The shared input look, from the design system in static/css/src.css. Written
# out rather than reaching for `.input` on the textareas, because a fully
# rounded pill reads badly on a box several lines tall.
INPUT = "input"
# Everything else on the card is a full pill; a box several lines tall reads
# badly that way, so a textarea keeps the same colors and focus ring but
# overrides just the corner radius back down to the smaller one. A utility
# class always beats a component class of the same specificity in Tailwind's
# layer order, so this is enough - no separate textarea styling to maintain.
TEXTAREA = INPUT + " rounded-sm resize-y"
# Visually hidden (not display:none, so it stays focusable and tabbable) -
# the pill next to it is what's actually seen. Toggling is pure CSS, driven
# by :has() in src.css, so an amenity pill works with no JavaScript at all.
CHECKBOX = "tag-toggle-input sr-only"

# Offered as a dropdown, but the field stays free text - an operator in a
# neighbourhood nobody listed here can just type it, and it is saved as typed.
BALI_AREAS = [
    "Canggu", "Pererenan", "Seminyak", "Kerobokan", "Umalas", "Legian", "Kuta",
    "Uluwatu", "Jimbaran", "Nusa Dua", "Sanur", "Denpasar", "Ubud", "Sidemen",
    "Amed", "Lovina", "Tabanan",
]

# Dots, commas and spaces are all used as thousand separators depending on who
# is typing, so all of them are stripped before a price is read as a number.
_SEPARATORS = re.compile(r"[.,\s]")


class IDRInput(forms.TextInput):
    """A plain box for typing a price into. Text rather than number, because
    a `type="number"` input refuses to hold thousand separators at all, and
    the operator is free to type "1.500.000", "1500000", or anything between.

    The friendly "Rp 1.500.000" reading appears live underneath as they type -
    see the `[data-idr-input]` handler in static/js/villa_form.js - rather
    than being forced into the box itself, so the cursor never has to jump
    around mid-word.
    """

    def __init__(self, attrs=None):
        defaults = {
            "class": INPUT, "inputmode": "numeric", "placeholder": "1500000",
            "data-idr-input": "true",
        }
        defaults.update(attrs or {})
        super().__init__(defaults)


class IDRField(forms.IntegerField):
    """A price in whole rupiah, typed however the operator likes.

    "1.500.000", "1,500,000", "1 500 000" and "1500000" all mean the same
    number, so all four are accepted and the separators are dropped before it
    is stored.
    """

    widget = IDRInput

    default_error_messages = {
        "invalid": _("Write the price in numbers only, like 1.500.000."),
        "min_value": _("A price can't be less than zero."),
    }

    def __init__(self, **kwargs):
        kwargs.setdefault("min_value", 0)
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = _SEPARATORS.sub("", value)
        return super().to_python(value)


class VillaForm(forms.ModelForm):
    """Step 1 - the property as a whole.

    Only three things are really needed to get going: what it's called, what
    kind of place it is, and roughly where. Everything else can wait, and the
    template says so by putting it in a lighter block below.

    Check-in and check-out times are optional here but never empty on file:
    left blank they fall back to the usual Bali times, so no other screen ever
    has to cope with a villa that has no check-in time.
    """

    class Meta:
        model = Villa
        fields = [
            "name", "property_type", "area", "address", "google_maps_url",
            "check_in_time", "check_out_time",
            "description_en", "description_id",
        ]
        labels = {
            "name": _("Name"),
            "property_type": _("Property type"),
            "area": _("Area"),
            "address": _("Address"),
            "google_maps_url": _("Google Maps link"),
            "check_in_time": _("Check-in time"),
            "check_out_time": _("Check-out time"),
            "description_en": _("Description (English)"),
            "description_id": _("Description (Indonesian)"),
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT, "placeholder": _("e.g. Villa Kenanga")}),
            "property_type": forms.Select(attrs={"class": INPUT}),
            "area": forms.TextInput(attrs={
                "class": INPUT, "list": "bali-areas", "autocomplete": "off",
                "placeholder": _("e.g. Canggu"),
            }),
            "address": forms.TextInput(attrs={
                "class": INPUT, "placeholder": _("Street address"),
            }),
            "google_maps_url": forms.URLInput(attrs={
                "class": INPUT, "placeholder": "https://maps.google.com/...",
            }),
            "check_in_time": forms.TimeInput(attrs={"class": INPUT, "type": "time"}, format="%H:%M"),
            "check_out_time": forms.TimeInput(attrs={"class": INPUT, "type": "time"}, format="%H:%M"),
            "description_en": forms.Textarea(attrs={
                "class": TEXTAREA, "rows": 3, "placeholder": _("A few sentences guests will see"),
            }),
            "description_id": forms.Textarea(attrs={
                "class": TEXTAREA, "rows": 3, "placeholder": _("A few sentences guests will see"),
            }),
        }
        error_messages = {
            "name": {"required": _("Give the villa a name.")},
            "google_maps_url": {"invalid": _("That doesn't look like a link. It should start with https://")},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # `area` is blank=True on the model so villas made in the admin or by a
        # script don't need one, but it is asked for here - knowing which part
        # of Bali a villa is in is most of what makes the villa list readable.
        self.fields["area"].required = True
        self.fields["area"].error_messages["required"] = _("Say which area it's in.")
        # Optional on the form even though the model always holds a time.
        self.fields["check_in_time"].required = False
        self.fields["check_out_time"].required = False

    def clean_check_in_time(self):
        return self.cleaned_data.get("check_in_time") or DEFAULT_CHECK_IN_TIME

    def clean_check_out_time(self):
        return self.cleaned_data.get("check_out_time") or DEFAULT_CHECK_OUT_TIME


class RoomCategoryForm(forms.ModelForm):
    """Step 2 - one kind of room.

    A villa rented out whole is one of these with a single room in it, so this
    same block covers both the one-villa case and a guesthouse with several
    kinds of room.

    `room_count` is not a column on the model. It says how many real rooms of
    this type should exist, and the view hands it to set_room_count(), which
    makes or removes them. See the RoomCategory docstring for why it is not
    stored.
    """

    room_count = forms.IntegerField(
        label=_("Number of rooms"),
        min_value=1, max_value=MAX_ROOMS_PER_TYPE, initial=1,
        widget=forms.NumberInput(attrs={"class": INPUT, "min": 1, "max": MAX_ROOMS_PER_TYPE}),
        error_messages={
            "required": _("Say how many rooms of this kind there are."),
            "min_value": _("There has to be at least one room of this kind."),
            "max_value": _("That's more rooms than we can add at once. Split it into two room types."),
        },
    )
    nightly_rate = IDRField(
        required=False, label=_("Nightly rate (IDR)"),
        widget=IDRInput(attrs={"placeholder": "1500000"}),
    )
    monthly_rate = IDRField(
        required=False, label=_("Monthly rate (IDR)"),
        widget=IDRInput(attrs={"placeholder": "18000000"}),
    )

    class Meta:
        model = RoomCategory
        fields = [
            "name", "room_count", "amenities",
            "size_sqm", "max_guests", "nightly_rate", "monthly_rate", "minimum_nights",
            "use_first_category_photos",
        ]
        labels = {
            # "name" carries no label of its own - it IS the card's title, see
            # _room_block.html, styled to read as plain bold text rather than
            # a boxed field with a question above it.
            "amenities": _("Amenities"),
            "size_sqm": _("Size (m²)"),
            "max_guests": _("Max guests"),
            "nightly_rate": _("Nightly rate (IDR)"),
            "monthly_rate": _("Monthly rate (IDR)"),
            "minimum_nights": _("Minimum nights"),
            "use_first_category_photos": _("Use the first room type's photos"),
        }
        widgets = {
            # Looks like a plain bold title until it's touched - see the
            # .title-input rules in src.css - not a labeled boxed field like
            # everything else on the card.
            "name": forms.TextInput(attrs={"class": "title-input", "placeholder": _("Standard")}),
            "amenities": forms.CheckboxSelectMultiple(attrs={"class": CHECKBOX}),
            "size_sqm": forms.NumberInput(attrs={"class": INPUT, "min": 1, "placeholder": "35"}),
            "max_guests": forms.NumberInput(attrs={"class": INPUT, "min": 1}),
            "minimum_nights": forms.NumberInput(attrs={"class": INPUT, "min": 1}),
        }
        error_messages = {
            "name": {"required": _("Give this kind of room a name.")},
            "minimum_nights": {"required": _("Say the fewest nights someone can book.")},
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        # Only the shared amenities and this operator's own - never another
        # operator's, even though they all live in one table.
        self.fields["amenities"].queryset = Amenity.available_to(organization)
        self.fields["amenities"].required = False
        self.fields["size_sqm"].required = False
        self.fields["max_guests"].required = False

        if self.instance.pk and "room_count" not in self.initial:
            self.initial["room_count"] = self.instance.rooms.count() or 1

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_max_guests(self):
        # Optional on the form, but the model column can't be empty - so a
        # blank box means "the usual two", not "unknown".
        return self.cleaned_data.get("max_guests") or 2


class BaseRoomCategoryFormSet(forms.BaseInlineFormSet):
    """The room types of one villa, all saved together.

    Blocks are added and removed through their own HTMX views rather than with
    a delete tickbox, so every form here stands for a room type that already
    exists. That is what lets a photo be uploaded to a block before the villa
    is finished: the block it belongs to is already a real row.
    """

    def __init__(self, *args, organization=None, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["organization"] = self.organization
        return kwargs

    def clean(self):
        """Two room types with the same name would make a villa's rooms
        impossible to tell apart, so the second one is refused - in plain
        words, on the block that caused it, rather than as Django's own
        wording at the top of the page.
        """
        super().clean()
        seen = {}
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            name = (form.cleaned_data.get("name") or "").strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                form.add_error(
                    "name",
                    _('You already have a room type called "%(name)s". Give this one a different name.')
                    % {"name": name},
                )
            seen[key] = form


RoomCategoryFormSet = inlineformset_factory(
    Villa, RoomCategory,
    form=RoomCategoryForm,
    formset=BaseRoomCategoryFormSet,
    extra=0,
    can_delete=False,
)


class CustomAmenityForm(forms.ModelForm):
    """An amenity an operator types in themselves.

    Stored under their organization, so it comes back as a ready-made option
    next time without ever appearing on anyone else's list. The one thing they
    type goes into both language fields - it is their own wording for their own
    villa, not interface copy for us to translate.
    """

    class Meta:
        model = Amenity
        fields = ["name_en"]
        widgets = {
            "name_en": forms.TextInput(attrs={
                "class": INPUT, "placeholder": _("e.g. Yoga deck"), "maxlength": 80,
            }),
        }
        error_messages = {"name_en": {"required": _("Type what it is first.")}}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_name_en(self):
        name = self.cleaned_data["name_en"].strip()
        if Amenity.available_to(self.organization).filter(name_en__iexact=name).exists():
            raise forms.ValidationError(_("That one is already on the list."))
        return name

    def save(self, commit=True):
        amenity = super().save(commit=False)
        amenity.organization = self.organization
        amenity.name_id = amenity.name_en
        if commit:
            amenity.save()
            logger.info(
                "Organization %s added their own amenity %s (%s)",
                self.organization.pk if self.organization else None,
                amenity.pk, amenity.name_en,
            )
        return amenity

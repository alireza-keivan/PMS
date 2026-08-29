from collections import namedtuple

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.villas.models import MAX_ROOMS_PER_TYPE, Amenity, RoomCategory, Villa

INPUT = "w-full rounded border border-sand-200 px-3 py-2 focus:border-teal-500 focus:outline-none"
TEXTAREA = INPUT + " h-24"


class VillaForm(forms.ModelForm):
    """Everything a villa needs on record, in one form.

    Mandatory: name, property type, at least one room type (handled outside
    this form - see parse_room_types below), at least one amenity, and a
    cover photo. Everything else is optional and lives behind "more details"
    in the template.

    `amenities` and `cover_photo` are not Villa model fields - amenities is a
    reverse many-to-many from Amenity, and photos live on their own
    VillaPhoto model - so both are handled explicitly in
    VillaCreateView.form_valid rather than by ModelForm's automatic save.
    A relational database has no way to enforce "at least one" on a
    many-to-many at the schema level, so the amenity requirement is real but
    lives here, in validation - not as a database constraint.
    """

    amenities = forms.ModelMultipleChoiceField(
        queryset=Amenity.objects.all(),
        required=True,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": _("Pick at least one amenity.")},
    )
    cover_photo = forms.ImageField(
        required=True,
        help_text=_("At least one photo is required."),
        error_messages={"required": _("Add at least one photo.")},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Editing an existing villa: it already has amenities and a cover
            # photo on file, so neither has to be resubmitted every time.
            self.fields["amenities"].initial = self.instance.amenities.all()
            self.fields["cover_photo"].required = False
            self.fields["cover_photo"].help_text = _("Leave empty to keep the current photo.")
            self.fields["cover_photo"].error_messages["required"] = _("Add at least one photo.")

    class Meta:
        model = Villa
        fields = [
            "name", "property_type",
            "address", "area", "bathrooms", "max_guests",
            "size_sqm", "google_maps_url",
            "check_in_time", "check_out_time", "min_nights",
            "base_nightly_rate", "base_monthly_rate",
            "description_en", "description_id",
            "is_listed_publicly",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT}),
            "property_type": forms.Select(attrs={"class": INPUT}),
            "address": forms.TextInput(attrs={"class": INPUT}),
            "area": forms.TextInput(attrs={"class": INPUT}),
            "bathrooms": forms.NumberInput(attrs={"class": INPUT, "min": 1}),
            "max_guests": forms.NumberInput(attrs={"class": INPUT, "min": 1}),
            "size_sqm": forms.NumberInput(attrs={"class": INPUT, "min": 1}),
            "google_maps_url": forms.URLInput(attrs={"class": INPUT, "placeholder": "https://maps.google.com/..."}),
            "check_in_time": forms.TimeInput(attrs={"class": INPUT, "type": "time"}),
            "check_out_time": forms.TimeInput(attrs={"class": INPUT, "type": "time"}),
            "min_nights": forms.NumberInput(attrs={"class": INPUT, "min": 1}),
            "base_nightly_rate": forms.NumberInput(attrs={"class": INPUT, "min": 0, "step": "0.01"}),
            "base_monthly_rate": forms.NumberInput(attrs={"class": INPUT, "min": 0, "step": "0.01"}),
            "description_en": forms.Textarea(attrs={"class": TEXTAREA}),
            "description_id": forms.Textarea(attrs={"class": TEXTAREA}),
            "is_listed_publicly": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-sand-300"}),
        }


class RoomCategoryForm(forms.ModelForm):
    """Add one room type, and the rooms that come with it."""

    count = forms.IntegerField(
        label=_("How many rooms"), min_value=1, max_value=MAX_ROOMS_PER_TYPE, initial=1,
        widget=forms.NumberInput(attrs={"class": INPUT, "min": 1, "max": MAX_ROOMS_PER_TYPE}),
    )

    def __init__(self, *args, villa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.villa = villa

    def clean_name(self):
        """Two types with the same name on one villa would make its rooms
        impossible to tell apart, so the second one is refused here.
        """
        name = self.cleaned_data["name"].strip()
        if self.villa and self.villa.room_categories.filter(name__iexact=name).exists():
            raise forms.ValidationError(_("This villa already has a room type with that name."))
        return name

    class Meta:
        model = RoomCategory
        fields = ["name"]
        labels = {"name": _("Room type")}
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT, "placeholder": _("e.g. Garden view")}),
        }


RoomTypeRow = namedtuple("RoomTypeRow", ["name", "count"])


def submitted_room_type_rows(post) -> list:
    """The room type rows exactly as they were typed, for re-rendering the
    add form after an error without losing anyone's work.
    """
    names = post.getlist("room_type_name")
    counts = post.getlist("room_type_count")
    return [
        {"name": name, "count": counts[i] if i < len(counts) else ""}
        for i, name in enumerate(names)
    ]


def parse_room_types(post):
    """Read the add-villa form's repeated "room type / how many" rows.

    Not a ModelForm: each row creates two kinds of object (a room type and
    its rooms) and the villa they belong to does not exist yet, so the rows
    are checked here and written in VillaCreateView.form_valid once it does.
    Returns (rows, errors), errors being plain sentences ready to show.
    """
    rows, errors, seen = [], [], set()

    for row in submitted_room_type_rows(post):
        name = row["name"].strip()
        raw_count = str(row["count"]).strip()

        if not name and not raw_count:
            continue  # an empty row the operator left behind - just skip it
        if not name:
            errors.append(_("Give every room type a name."))
            continue
        if name.casefold() in seen:
            errors.append(
                _('You have two room types called "%(name)s" - give one of them a different name.')
                % {"name": name}
            )
            continue

        try:
            count = int(raw_count)
        except ValueError:
            count = 0
        if count < 1 or count > MAX_ROOMS_PER_TYPE:
            errors.append(
                _('Say how many "%(name)s" rooms there are, from 1 to %(most)s.')
                % {"name": name, "most": MAX_ROOMS_PER_TYPE}
            )
            continue

        seen.add(name.casefold())
        rows.append(RoomTypeRow(name, count))

    if not rows and not errors:
        errors.append(_("Add at least one room type, and how many rooms of it this villa has."))
    return rows, errors

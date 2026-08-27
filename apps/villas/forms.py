from django import forms
from django.utils.translation import gettext_lazy as _

from apps.villas.models import Amenity, Villa

INPUT = "w-full rounded border border-sand-200 px-3 py-2 focus:border-teal-500 focus:outline-none"
TEXTAREA = INPUT + " h-24"


class VillaForm(forms.ModelForm):
    """Everything a villa needs on record, in one form.

    Mandatory: name, property type, bedrooms, at least one amenity, and a
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
            "name", "property_type", "bedrooms",
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
            "bedrooms": forms.NumberInput(attrs={"class": INPUT, "min": 1}),
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

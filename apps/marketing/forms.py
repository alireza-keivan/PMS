"""The direct booking form on a villa's public page.

Everything a visitor types arrives here, and everything that can be wrong with
it is decided here rather than in the view - so the view is left with two
outcomes, and every rejection has one place to be logged and one place to be
worded. See apps.marketing.views.

What this form does NOT do: hold a room, write to a calendar, or take money.
It checks the dates against real bookings so the page can be honest about
availability, then records a request for the operator to answer. CLAUDE.md
rule 5 - nothing public writes to live inventory.
"""

import logging
from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.bookings.services import find_available_room
from apps.core.utils import title_words
from apps.marketing.models import (
    EXPERIENCE_DESCRIPTION_MAX_LENGTH,
    BookingEnquiry,
    Experience,
)

logger = logging.getLogger(__name__)

# Nobody is booking a villa for next year and a half from a phone, and a date
# typed with the wrong year is far more likely than a real request that far
# out. Keeps the availability scan bounded too.
MAX_NIGHTS = 90


class DateInput(forms.DateInput):
    """A native date box. No JavaScript picker: the phone's own is better than
    anything we would ship, and it costs nothing to download.
    """

    input_type = "date"


class BookingEnquiryForm(forms.ModelForm):
    """Needs the villa it belongs to - the minimum stay, the price and what
    counts as available all come off that villa's room types, never off
    anything the visitor sent.
    """

    class Meta:
        model = BookingEnquiry
        fields = [
            "room_category", "check_in", "check_out", "guest_count",
            "guest_name", "guest_email", "guest_phone", "message",
        ]
        widgets = {
            "check_in": DateInput(attrs={"class": "input"}),
            "check_out": DateInput(attrs={"class": "input"}),
            "guest_count": forms.NumberInput(attrs={"class": "input", "min": 1}),
            "guest_name": forms.TextInput(attrs={"class": "input", "autocomplete": "name"}),
            "guest_email": forms.EmailInput(attrs={"class": "input", "autocomplete": "email"}),
            "guest_phone": forms.TextInput(attrs={"class": "input", "autocomplete": "tel"}),
            "message": forms.Textarea(attrs={"class": "input rounded-md", "rows": 3}),
        }
        labels = {
            "room_category": _("Which room"),
            "check_in": _("Arriving"),
            "check_out": _("Leaving"),
            "guest_count": _("Guests"),
            "guest_name": _("Your name"),
            "guest_email": _("Email"),
            "guest_phone": _("WhatsApp number"),
            "message": _("Anything we should know?"),
        }

    def __init__(self, *args, villa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.villa = villa
        # Only this villa's own room types, so a posted id belonging to another
        # villa - or another operator entirely - is rejected by the field
        # itself rather than by a check somebody could forget to write.
        self.fields["room_category"].queryset = villa.room_categories.all()
        self.fields["room_category"].empty_label = _("Any room")
        self.fields["room_category"].required = False
        self.fields["room_category"].widget.attrs["class"] = "input"
        # One of the two has to be there or nobody can be answered, but making
        # both required loses the guest who only uses WhatsApp.
        self.fields["guest_email"].required = False
        self.fields["guest_phone"].required = False

    # The one place that decides which room types could take this request.
    def _candidate_categories(self, category):
        if category is not None:
            return [category]
        return list(self.villa.room_categories.all())

    def clean_check_in(self):
        check_in = self.cleaned_data["check_in"]
        if check_in < date.today():
            raise forms.ValidationError(_("That date has already passed."))
        return check_in

    def clean(self):
        cleaned = super().clean()
        check_in, check_out = cleaned.get("check_in"), cleaned.get("check_out")
        category = cleaned.get("room_category")
        guests = cleaned.get("guest_count")

        if not (cleaned.get("guest_email") or cleaned.get("guest_phone")):
            raise forms.ValidationError(
                _("Please leave an email or a WhatsApp number so we can reply.")
            )

        if not check_in or not check_out:
            return cleaned

        nights = (check_out - check_in).days
        if nights < 1:
            self.add_error("check_out", _("The leaving date has to be after the arriving date."))
            return cleaned
        if nights > MAX_NIGHTS:
            self.add_error(
                "check_out",
                _("That is a very long stay. Please message the owner directly instead."),
            )
            return cleaned

        candidates = self._candidate_categories(category)
        if not candidates:
            # No room types on the villa at all - there is nothing to book.
            raise forms.ValidationError(_("This villa is not taking bookings right now."))

        # Rejections are recorded on the form as `rejection` so the view can
        # log exactly why, in the words the guest was actually shown.
        long_enough = [c for c in candidates if nights >= c.minimum_nights]
        if not long_enough:
            shortest = min(c.minimum_nights for c in candidates)
            self.rejection = f"below minimum stay ({nights} < {shortest})"
            self.add_error("check_out", _("The shortest stay here is %(nights)s nights.") % {
                "nights": shortest,
            })
            return cleaned

        big_enough = [c for c in long_enough if guests is None or guests <= c.max_guests]
        if not big_enough:
            largest = max(c.max_guests for c in long_enough)
            self.rejection = f"too many guests ({guests} > {largest})"
            self.add_error("guest_count", _("These rooms sleep %(count)s people at most.") % {
                "count": largest,
            })
            return cleaned

        # Real availability, checked against real bookings. Read-only: this
        # only ever asks whether a room is free, it never takes one.
        self.available_category = None
        next_free = None
        for candidate in big_enough:
            # The third value is the room shuffle that would be needed - an
            # enquiry takes no room, so nothing is moved here. It is planned
            # for real when the manager turns the enquiry into a booking.
            room, freed_on, _moves = find_available_room(candidate, check_in, check_out)
            if room is not None:
                self.available_category = candidate
                break
            if freed_on and (next_free is None or freed_on < next_free):
                next_free = freed_on

        if self.available_category is None:
            self.rejection = f"no room free {check_in} to {check_out}"
            self.next_free_date = next_free
            raise forms.ValidationError(
                _("These dates are not available. Try a few days earlier or later.")
            )

        # The room type that can actually take them is what gets recorded, so
        # the operator reading this is not left guessing which one was meant.
        cleaned["room_category"] = self.available_category
        return cleaned

    # Set by clean() when something was wrong; the view logs it.
    rejection = ""
    next_free_date = None
    available_category = None


class ExperienceForm(forms.ModelForm):
    """One local activity on a villa's "Things to do nearby" section
    (feature #8). Edited from the villa's own edit page - see
    apps.villas.views - rather than only through the admin.
    """

    # Read by the template to draw the live letter counter.
    description_max_length = EXPERIENCE_DESCRIPTION_MAX_LENGTH

    class Meta:
        model = Experience
        fields = [
            "name_en", "name_id", "description_en", "description_id", "photo",
            "operator_name", "operator_phone", "commission_percent",
        ]
        widgets = {
            "name_en": forms.TextInput(attrs={"class": "input", "placeholder": _("e.g. Sunset cooking class")}),
            "name_id": forms.TextInput(attrs={"class": "input"}),
            # Deliberately no "maxlength" attribute: the browser would
            # silently swallow the extra letters mid-word. Letting people go
            # over and showing a warning is clearer than a box that just
            # stops accepting typing with no explanation.
            "description_en": forms.Textarea(attrs={"class": "input rounded-md", "rows": 3}),
            "description_id": forms.Textarea(attrs={"class": "input rounded-md", "rows": 3}),
            "operator_name": forms.TextInput(attrs={"class": "input"}),
            "operator_phone": forms.TextInput(attrs={"class": "input", "autocomplete": "tel"}),
            "commission_percent": forms.NumberInput(attrs={"class": "input", "min": 0, "max": 100, "step": "0.01"}),
        }
        labels = {
            "name_en": _("Name (English)"),
            "name_id": _("Name (Indonesian)"),
            "description_en": _("Description (English)"),
            "description_id": _("Description (Indonesian)"),
            "photo": _("Photo"),
            "operator_name": _("Operator name"),
            "operator_phone": _("Operator phone"),
            "commission_percent": _("Commission (%)"),
        }
        error_messages = {
            "name_en": {"required": _("Give this activity a name.")},
            "description_en": {"max_length": _("Please keep this to %(limit_value)d letters or fewer.")},
            "description_id": {"max_length": _("Please keep this to %(limit_value)d letters or fewer.")},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for optional in ("name_id", "description_en", "description_id", "operator_name", "operator_phone"):
            self.fields[optional].required = False
        self.fields["commission_percent"].required = False
        # Require a photo when adding a new activity. When editing one that
        # already has a photo, don't force re-upload just to save the form.
        if not (self.instance and self.instance.pk and self.instance.photo):
            self.fields["photo"].required = True

    def clean_name_en(self):
        return title_words(self.cleaned_data["name_en"])

    def clean_name_id(self):
        return title_words(self.cleaned_data.get("name_id", ""))

    def clean_commission_percent(self):
        # Optional on the form, but the model column can't be empty - so a
        # blank box means "no commission", not "unknown".
        return self.cleaned_data.get("commission_percent") or 0

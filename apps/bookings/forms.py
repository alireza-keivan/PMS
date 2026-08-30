"""The Add Reservation form.

One plain form (not a ModelForm) because a single submission writes to three
models - Guest, Booking, and BookingPayment - not one. See
apps.bookings.views.ReservationCreateView for how it's saved.
"""

import logging

from django import forms
from django.conf import settings
from django.utils import formats
from django.utils.translation import gettext_lazy as _

from apps.bookings.models import Booking
from apps.bookings.services import find_available_room
from apps.guests.constants import NATIONALITY_CHOICES
from apps.villas.forms import INPUT, TEXTAREA, IDRField, IDRInput
from apps.villas.models import RoomCategory, Villa

logger = logging.getLogger(__name__)

# Status choices for a reservation entered by hand - BLOCKED is an iCal-only
# concept (a date range with no guest behind it), never something staff pick.
STATUS_CHOICES = [
    (Booking.Status.CONFIRMED, _("Confirmed")),
    (Booking.Status.CANCELLED, _("Cancelled")),
]


class ReservationForm(forms.Form):
    """Villa and room_type querysets are scoped by the view to whatever villas
    the logged-in user can actually see - never the raw Villa/RoomCategory
    tables. `hide_money` drops the three price fields entirely for a staff
    member who isn't allowed to see money (Membership.can_see_money), rather
    than just hiding them in the template - so there's nothing to strip out
    of a hand-crafted POST either.
    """

    villa = forms.ModelChoiceField(
        queryset=Villa.objects.none(), label=_("Villa"),
        empty_label=_("Choose a villa"),
        widget=forms.Select(attrs={"class": INPUT, "x-model": "villaId", "@change": "onVillaChange()"}),
        error_messages={"required": _("Choose which villa this booking is for.")},
    )
    # Rendered by hand in add.html (x-for over reservation_form.js's
    # roomTypeOptions) rather than through this widget, so the visible list
    # follows whichever villa is picked without a server round trip - see
    # ReservationForm.__init__ for why the field (and its queryset) still
    # exists here regardless: it's what validates the posted value.
    room_type = forms.ModelChoiceField(
        queryset=RoomCategory.objects.none(), label=_("Room type"),
        empty_label=_("Choose a room type"),
        error_messages={"required": _("Choose which room type this booking is for.")},
    )
    check_in = forms.DateField(
        label=_("Check-in date"),
        widget=forms.DateInput(attrs={"class": INPUT, "type": "date"}),
        error_messages={"required": _("Say when the guest checks in.")},
    )
    check_out = forms.DateField(
        label=_("Check-out date"),
        widget=forms.DateInput(attrs={"class": INPUT, "type": "date"}),
        error_messages={"required": _("Say when the guest checks out.")},
    )
    guest_count = forms.IntegerField(
        label=_("Number of guests"), min_value=1, initial=2,
        widget=forms.NumberInput(attrs={"class": INPUT, "min": 1}),
        error_messages={"required": _("Say how many guests are staying.")},
    )

    full_name = forms.CharField(
        label=_("Guest full name"), max_length=160,
        widget=forms.TextInput(attrs={"class": INPUT, "placeholder": _("e.g. Sarah Mitchell")}),
        error_messages={"required": _("Give the guest's name.")},
    )
    phone = forms.CharField(
        label=_("Phone number"), max_length=32, required=False,
        widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "+62"}),
    )
    email = forms.EmailField(
        label=_("Email"), required=False,
        widget=forms.EmailInput(attrs={"class": INPUT, "placeholder": "guest@email.com"}),
    )
    nationality = forms.ChoiceField(
        label=_("Nationality"), required=False,
        choices=[("", _("Choose a nationality"))] + NATIONALITY_CHOICES,
        widget=forms.Select(attrs={"class": INPUT}),
    )
    language = forms.ChoiceField(
        label=_("Preferred language"), required=False,
        choices=[("", _("Choose a language"))] + list(settings.LANGUAGES),
        widget=forms.Select(attrs={"class": INPUT}),
    )

    booked_through = forms.ChoiceField(
        label=_("Booked through"),
        choices=[("", _("Choose one"))] + Booking.Channel.choices,
        widget=forms.Select(attrs={"class": INPUT}),
        error_messages={"required": _("Say how this booking came in.")},
    )
    status = forms.ChoiceField(
        label=_("Status"), choices=STATUS_CHOICES, initial=Booking.Status.CONFIRMED,
        widget=forms.Select(attrs={"class": INPUT}),
    )

    nightly_rate = IDRField(
        required=False, label=_("Nightly rate (IDR)"),
        widget=IDRInput(attrs={"placeholder": "1500000"}),
    )
    # x-model feeds reservation_form.js's live balance line - see add.html.
    total_amount = IDRField(
        required=False, label=_("Total amount (IDR)"),
        widget=IDRInput(attrs={"placeholder": "6000000", "x-model": "totalRaw"}),
    )
    amount_paid = IDRField(
        required=False, label=_("Amount paid (IDR)"),
        widget=IDRInput(attrs={"placeholder": "0", "x-model": "paidRaw"}),
    )

    notes = forms.CharField(
        label=_("Notes"), required=False,
        widget=forms.Textarea(attrs={
            "class": TEXTAREA, "rows": 2,
            "placeholder": _("Anything else worth knowing about this booking"),
        }),
    )

    def __init__(self, *args, villas, hide_money=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.villas = villas
        self.hide_money = hide_money
        self.available_room = None
        self.next_free_date = None

        villa_ids = [v.id for v in villas]
        self.fields["villa"].queryset = Villa.objects.filter(id__in=villa_ids)
        # Every allowed villa's room types, not just the selected one's - a
        # dependent select filters these client-side (see reservation_form.js),
        # and the full scoped set is still what keeps a POST for a villa/room
        # combination that don't belong together from validating below.
        self.fields["room_type"].queryset = RoomCategory.objects.filter(
            villa_id__in=villa_ids
        ).select_related("villa")

        # A staff member who can't see money never gets sent these fields at
        # all, so a hand-crafted POST including them still has nothing to read.
        if hide_money:
            del self.fields["nightly_rate"]
            del self.fields["total_amount"]
            del self.fields["amount_paid"]

    def clean(self):
        cleaned_data = super().clean()

        villa = cleaned_data.get("villa")
        room_type = cleaned_data.get("room_type")
        if villa and room_type and room_type.villa_id != villa.id:
            self.add_error("room_type", _("Choose a room type that belongs to the selected villa."))
            room_type = None

        check_in = cleaned_data.get("check_in")
        check_out = cleaned_data.get("check_out")
        if check_in and check_out and check_out <= check_in:
            self.add_error("check_out", _("Check-out has to be after check-in."))
            check_out = None

        if room_type and check_in and check_out:
            room, next_free_date = find_available_room(room_type, check_in, check_out)
            if room is None:
                self.next_free_date = next_free_date
                message = _(
                    "All %(room_type)s rooms in this period are booked. The next free "
                    "time starts at %(date)s. Please check the calendar."
                ) % {
                    "room_type": room_type.name,
                    "date": formats.date_format(next_free_date, "d M Y") if next_free_date else "?",
                }
                self.add_error(None, message)
            else:
                self.available_room = room

        if not cleaned_data.get("phone") and not cleaned_data.get("email"):
            self.add_error(None, _("Add a phone number or email so staff can reach the guest."))

        return cleaned_data

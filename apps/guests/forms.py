"""The one form a guest ever fills in.

Deliberately tiny: what do you need, and anything you want to add. Nothing
about who they are - the link already answered that, and asking a guest to
retype their own name would be the login we decided not to build.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.guests.models import GuestRequest

# Same input look as the rest of the product (static/css/src.css), but a
# textarea several lines tall reads badly as a full pill, so it keeps the
# colors and the focus ring and drops the corner radius - the same trade-off
# apps/villas/forms.py makes for its own boxes.
TEXTAREA = "input rounded-sm resize-y"

# Everything a guest can ask for is on screen at once as tappable cards, so a
# guest sees the whole list without opening anything. Radios rather than a
# dropdown: one thumb, one tap, no scrolling picker.
#
# Visually hidden rather than display:none, so it stays focusable and tabbable
# - the .pick card next to it is what's actually seen, and the checked/focused
# looks are pure CSS via :has() in static/css/src.css. No JavaScript involved.
KIND_RADIO = "pick-input sr-only"


class GuestRequestForm(forms.ModelForm):
    """What the guest needs, in two fields.

    `kind` is required; `message` is not - "cleaning" on its own is a complete
    request and making someone write a sentence to send it would lose requests.
    """

    class Meta:
        model = GuestRequest
        fields = ["kind", "message"]
        widgets = {
            "kind": forms.RadioSelect(attrs={"class": KIND_RADIO}),
            "message": forms.Textarea(
                attrs={
                    "class": TEXTAREA,
                    "rows": 3,
                    "placeholder": _("Anything else we should know? (optional)"),
                }
            ),
        }
        labels = {
            "kind": _("What do you need?"),
            "message": _("Tell us more"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Django puts a blank "---------" choice on a ModelForm field with a
        # default-less CharField; as radio buttons that would render as a real,
        # tappable, meaningless option.
        self.fields["kind"].choices = GuestRequest.Kind.choices
        self.fields["kind"].error_messages["required"] = _("Pick what you need first.")
        self.fields["message"].required = False

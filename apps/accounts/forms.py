"""Forms for signing in and for the first screen after that."""

from django import forms
from django.utils.translation import gettext_lazy as _

INPUT_CLASSES = (
    "w-full rounded border border-sand-200 px-3 py-2 "
    "focus:border-teal-500 focus:outline-none"
)


class OnboardingForm(forms.Form):
    """One question, asked once: what the person's business is called.

    Everything else about the business - villas, staff, sync tier - is set up
    afterwards, from screens built for it. Asking for any of it here would put
    a form in front of someone who has not seen the product yet.
    """

    name = forms.CharField(
        label=_("What is your business called?"),
        max_length=160,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASSES,
                "placeholder": _("For example: Canggu Coastal Villas"),
                "autofocus": True,
            }
        ),
    )

    def clean_name(self):
        return self.cleaned_data["name"].strip()

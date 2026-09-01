"""Forms for the "add staff" screen a Manager uses from their dashboard."""

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

INPUT_CLASSES = (
    "w-full rounded border border-sand-200 px-3 py-2 "
    "focus:border-teal-500 focus:outline-none"
)


class StaffCreateForm(forms.Form):
    """Everything needed to log this staff member in, plus which villas they
    can see. Villas are limited to the organization's own live villas by the
    view, not here - the form doesn't know which organization it's for.
    """

    full_name = forms.CharField(
        label=_("Name"), max_length=150, required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASSES}),
    )
    email = forms.EmailField(
        label=_("Email address"),
        widget=forms.EmailInput(attrs={"class": INPUT_CLASSES}),
    )
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASSES}),
        help_text=_("Share this with them - they'll log in with this email and password."),
    )
    villas = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Villas this person can see"),
        help_text=_("Leave everything unchecked to give them no villas yet - you can change this later."),
    )

    def __init__(self, *args, villa_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["villas"].queryset = villa_queryset

    def clean_password(self):
        password = self.cleaned_data["password"]
        try:
            validate_password(password)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return password


class StaffVillasForm(forms.Form):
    """Editing an existing staff member: only their villa access changes -
    email and password are managed by the person themselves once they have
    an account.
    """

    villas = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Villas this person can see"),
        help_text=_("Leave everything unchecked to give them no villas."),
    )

    def __init__(self, *args, villa_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["villas"].queryset = villa_queryset

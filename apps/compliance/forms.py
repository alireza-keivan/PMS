from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.compliance.models import ComplianceDocument, ComplianceDocumentType
from apps.villas.models import Villa

INPUT = "input"
TEXTAREA = "input h-24 rounded-2xl py-2"


class ComplianceDocumentForm(forms.ModelForm):
    """Villa choices are passed in by the view (apps.compliance.views), scoped
    to whatever villas the logged-in user can actually see - never the raw
    Villa table, and never another organization's villas.

    document_type works the same way for the type dropdown: global types plus
    this organization's own custom ones. A client can also skip the dropdown
    and fill in new_type_name/new_type_reminder_days instead, which creates a
    reusable custom type for their organization on save() - see clean().
    """

    new_type_name = forms.CharField(
        required=False, max_length=120, label=_("Or add your own type"),
        widget=forms.TextInput(attrs={"class": INPUT}),
    )
    new_type_reminder_days = forms.IntegerField(
        required=False, min_value=1, label=_("Remind us this many days before it expires"),
        widget=forms.NumberInput(attrs={"class": INPUT}),
    )

    class Meta:
        model = ComplianceDocument
        fields = [
            "document_type", "villa", "reference_number", "file",
            "issued_on", "expires_on", "reminder_days", "notes",
        ]
        widgets = {
            "document_type": forms.Select(attrs={"class": INPUT}),
            "villa": forms.Select(attrs={"class": INPUT}),
            "reference_number": forms.TextInput(attrs={"class": INPUT}),
            "file": forms.ClearableFileInput(attrs={"class": "text-sm"}),
            "issued_on": forms.DateInput(attrs={"class": INPUT, "type": "date"}),
            "expires_on": forms.DateInput(attrs={"class": INPUT, "type": "date"}),
            "reminder_days": forms.NumberInput(attrs={"class": INPUT, "min": 1}),
            "notes": forms.Textarea(attrs={"class": TEXTAREA}),
        }
        help_texts = {
            "villa": _("Leave blank if this covers the whole business."),
        }

    def __init__(self, *args, villas=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._organization = organization

        # apps.bookings.services.scoped_villas returns a plain list (it's
        # already been through Python-side role/villa scoping), not a
        # queryset - ModelChoiceField needs a queryset, so rebuild one
        # scoped to just those ids rather than re-deriving access rules here.
        villa_ids = [v.id for v in villas] if villas is not None else []
        self.fields["villa"].queryset = Villa.objects.filter(id__in=villa_ids)
        self.fields["villa"].required = False

        self.fields["document_type"].queryset = ComplianceDocumentType.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True), is_active=True,
        )
        self.fields["document_type"].required = False

    def clean(self):
        cleaned_data = super().clean()
        document_type = cleaned_data.get("document_type")
        new_type_name = cleaned_data.get("new_type_name")
        if not document_type and not new_type_name:
            raise forms.ValidationError(_("Choose a document type, or add your own."))
        return cleaned_data

    def save(self, commit=True):
        new_type_name = self.cleaned_data.get("new_type_name")
        if new_type_name:
            self.instance.document_type = ComplianceDocumentType.objects.create(
                organization=self._organization,
                name=new_type_name,
                default_reminder_days=self.cleaned_data.get("new_type_reminder_days") or 60,
            )
        return super().save(commit=commit)

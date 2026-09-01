"""Licence vault + action-needed status view (features #14 and #16), and the
STM police-report reminder (#15). Deliberately read-heavy - CLAUDE.md's build
order calls this step "mostly reading and displaying data". The one real
write here is staff marking a police report done, which is the reminder's
whole point (see PoliceReport's docstring) - it's not booking/availability
data, so CLAUDE.md rule 5's confirmation requirement doesn't apply to it.
"""

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, TemplateView, View

from apps.compliance.forms import ComplianceDocumentForm
from apps.compliance.models import ComplianceDocument, ComplianceDocumentType, PoliceReport
from apps.organizations.mixins import ManagerRequiredMixin
from apps.organizations.permissions import is_manager
from apps.organizations.scoping import scoped_villas

# STM deadlines are 24 hours after check-in, so "upcoming" is naturally a
# short window - this keeps the action-needed count matching feature #16's
# "needs attention this week" framing instead of including reports for
# bookings that are still months away.
POLICE_REPORT_HORIZON_DAYS = 7


class ActionNeededView(LoginRequiredMixin, TemplateView):
    template_name = "compliance/action_needed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        if org is None:
            context["no_organization"] = True
            return context

        documents_needing_attention = _documents_needing_attention(self.request)
        police_reports = _upcoming_police_reports(self.request)

        context.update(
            no_organization=False,
            today=timezone.localdate(),
            documents_needing_attention=documents_needing_attention,
            police_reports=police_reports,
            action_count=len(documents_needing_attention) + police_reports.count(),
        )
        return context


class DocumentListView(LoginRequiredMixin, ListView):
    template_name = "compliance/documents.html"
    context_object_name = "documents"

    def get_queryset(self):
        org = self.request.organization
        if org is None:
            return ComplianceDocument.objects.none()
        villas, _membership = scoped_villas(self.request)
        return (
            ComplianceDocument.objects.filter(organization=org)
            .filter(Q(villa_id__in=[v.id for v in villas]) | Q(villa__isnull=True))
            .select_related("villa")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["no_organization"] = self.request.organization is None
        context["is_manager"] = is_manager(self.request.user)
        return context


class DocumentCreateView(ManagerRequiredMixin, CreateView):
    model = ComplianceDocument
    form_class = ComplianceDocumentForm
    template_name = "compliance/document_form.html"
    success_url = reverse_lazy("compliance:documents")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.organization is None:
            return redirect("compliance:documents")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        villas, _membership = scoped_villas(self.request)
        kwargs["villas"] = villas
        kwargs["organization"] = self.request.organization
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        types = ComplianceDocumentType.objects.filter(
            Q(organization=self.request.organization) | Q(organization__isnull=True), is_active=True,
        )
        context["document_type_meta"] = json.dumps({
            str(t.id): {
                "validity_days": t.default_validity_days,
                "reminder_days": t.default_reminder_days,
                "template_url": t.template_file.url if t.template_file else None,
            }
            for t in types
        })
        return context

    def form_valid(self, form):
        form.instance.organization = self.request.organization
        response = super().form_valid(form)
        messages.success(self.request, _("Document added."))
        return response


class MarkPoliceReportDoneView(LoginRequiredMixin, View):
    def post(self, request, pk):
        org = request.organization
        report = get_object_or_404(
            PoliceReport.objects.filter(organization=org) if org else PoliceReport.objects.none(),
            pk=pk,
        )
        report.status = PoliceReport.Status.FILED
        report.marked_done_by = request.user
        report.marked_done_at = timezone.now()
        report.save(update_fields=["status", "marked_done_by", "marked_done_at"])

        if request.htmx:
            action_count = len(_documents_needing_attention(request)) + _upcoming_police_reports(request).count()
            return render(request, "compliance/_police_report_done.html", {"action_count": action_count})

        messages.success(request, _("Marked as done."))
        return redirect("compliance:action_needed")


def _documents_needing_attention(request) -> list:
    org = request.organization
    villas, _membership = scoped_villas(request)
    documents = (
        ComplianceDocument.objects.filter(organization=org)
        .filter(Q(villa_id__in=[v.id for v in villas]) | Q(villa__isnull=True))
        .select_related("villa")
    )
    return sorted(
        (d for d in documents if d.needs_attention),
        key=lambda d: (d.expires_on is None, d.expires_on),
    )


def _upcoming_police_reports(request):
    org = request.organization
    villas, _membership = scoped_villas(request)
    horizon = timezone.now() + timedelta(days=POLICE_REPORT_HORIZON_DAYS)
    return (
        PoliceReport.objects.filter(
            organization=org, booking__villa_id__in=[v.id for v in villas],
            status=PoliceReport.Status.NEEDED, deadline__lte=horizon,
        )
        .select_related("guest", "booking", "booking__villa")
        .order_by("deadline")
    )

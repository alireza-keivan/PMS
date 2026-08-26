from django.contrib import admin

from apps.compliance.models import ComplianceDocument, PoliceReport


@admin.register(ComplianceDocument)
class ComplianceDocumentAdmin(admin.ModelAdmin):
    list_display = ("kind", "villa", "reference_number", "expires_on", "needs_attention")
    list_filter = ("organization", "kind")


@admin.register(PoliceReport)
class PoliceReportAdmin(admin.ModelAdmin):
    list_display = ("deadline", "guest", "booking", "status", "is_overdue")
    list_filter = ("organization", "status")

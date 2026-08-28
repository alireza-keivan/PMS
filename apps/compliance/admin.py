from django.contrib import admin

from apps.compliance.models import ComplianceDocument, ComplianceDocumentType, PoliceReport


@admin.register(ComplianceDocumentType)
class ComplianceDocumentTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "default_validity_days", "default_reminder_days", "is_active")
    list_filter = ("organization", "is_active")


@admin.register(ComplianceDocument)
class ComplianceDocumentAdmin(admin.ModelAdmin):
    list_display = ("document_type", "villa", "reference_number", "expires_on", "needs_attention")
    list_filter = ("organization", "document_type")


@admin.register(PoliceReport)
class PoliceReportAdmin(admin.ModelAdmin):
    list_display = ("deadline", "guest", "booking", "status", "is_overdue")
    list_filter = ("organization", "status")

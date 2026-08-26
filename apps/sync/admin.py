from django.contrib import admin

from apps.sync.models import RawPayload, SyncAccount, SyncRun


@admin.register(SyncAccount)
class SyncAccountAdmin(admin.ModelAdmin):
    list_display = ("label", "provider", "villa", "is_active", "last_success_at")
    list_filter = ("organization", "provider", "is_active")


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "account", "trigger", "result", "bookings_created", "bookings_updated")
    list_filter = ("organization", "trigger", "result")


@admin.register(RawPayload)
class RawPayloadAdmin(admin.ModelAdmin):
    list_display = ("created_at", "account", "endpoint", "processed_at")
    list_filter = ("organization", "account")
    readonly_fields = ("body",)

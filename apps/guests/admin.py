from django.contrib import admin

from apps.guests.models import Guest, GuestActivity, GuestFeedback, GuestRequest


class GuestActivityInline(admin.TabularInline):
    model = GuestActivity
    extra = 0
    fields = ("occurred_at", "kind", "subject", "villa")
    readonly_fields = fields
    can_delete = False
    ordering = ("-occurred_at",)

    def has_add_permission(self, request, obj=None):
        return False  # append-only, written by apps.guests.services.log_activity


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ("full_name", "nationality", "total_stays", "last_seen", "organization")
    list_filter = ("organization", "nationality")
    search_fields = ("full_name", "email", "phone")
    inlines = [GuestActivityInline]


@admin.register(GuestActivity)
class GuestActivityAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "guest", "kind", "subject", "villa")
    list_filter = ("organization", "kind", "villa")
    search_fields = ("guest__full_name", "subject")
    date_hierarchy = "occurred_at"


@admin.register(GuestRequest)
class GuestRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "guest", "kind", "status", "assigned_to", "notified_at")
    list_filter = ("organization", "kind", "status")


admin.site.register(GuestFeedback)

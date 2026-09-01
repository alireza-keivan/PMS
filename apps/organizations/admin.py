from django.contrib import admin

from apps.organizations.models import Membership, Organization


class MembershipInline(admin.TabularInline):
    """For fixing up an existing membership (e.g. its assigned villas).

    Don't use this to add a new staff member - it only creates the
    Membership row, not the Staff Group membership that makes villa scoping
    apply (see apps.organizations.permissions), and it can link a user who
    already has a Manager role elsewhere. Use the "Add staff" screen in the
    dashboard (apps.organizations.views.StaffCreateView) instead - that's
    the one place that gets both right.
    """

    model = Membership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "plan", "sync_tier", "default_currency", "is_active")
    list_filter = ("plan", "sync_tier", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MembershipInline]

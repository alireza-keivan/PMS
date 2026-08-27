from django.contrib import admin

from apps.organizations.models import Membership, Organization


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "plan", "sync_tier", "default_currency", "is_active")
    list_filter = ("plan", "sync_tier", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MembershipInline]

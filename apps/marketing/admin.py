from django.contrib import admin

from apps.marketing.models import BookingEnquiry, Experience, RateSnapshot

admin.site.register(Experience)
admin.site.register(RateSnapshot)


@admin.register(BookingEnquiry)
class BookingEnquiryAdmin(admin.ModelAdmin):
    """The ops panel for direct booking requests - see CLAUDE.md: the Django
    admin is the internal screen for this, so there is no custom staff page.
    """

    list_display = ("guest_name", "villa", "check_in", "check_out", "guest_count", "is_handled")
    list_filter = ("is_handled", "organization", "villa")
    search_fields = ("guest_name", "guest_email", "guest_phone")
    date_hierarchy = "check_in"

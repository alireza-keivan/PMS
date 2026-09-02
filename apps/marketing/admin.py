from django.contrib import admin

from apps.marketing.models import BookingEnquiry, Experience, RateSnapshot


@admin.register(Experience)
class ExperienceAdmin(admin.ModelAdmin):
    """Local activities shown on a villa's "Things to do nearby" section
    (feature #8). Also reachable, and addable, straight from the villa's own
    admin page - see ExperienceInline in apps.villas.admin.
    """

    list_display = ("name_en", "operator_name", "commission_percent", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("name_en", "name_id", "operator_name")
    filter_horizontal = ("villas",)
    fields = (
        "name_en", "name_id",
        "description_en", "description_id",
        "photo",
        "operator_name", "operator_phone", "commission_percent",
        "villas", "is_active",
    )


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

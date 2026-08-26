from django.contrib import admin

from apps.core.calendar import BaliHoliday


@admin.register(BaliHoliday)
class BaliHolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "impact")
    list_filter = ("impact",)
    date_hierarchy = "date"

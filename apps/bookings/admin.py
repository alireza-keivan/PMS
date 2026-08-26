from django.contrib import admin

from apps.bookings.models import Booking, BookingPayment


class PaymentInline(admin.TabularInline):
    model = BookingPayment
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("check_in", "check_out", "villa", "guest", "channel", "status", "source_detail")
    list_filter = ("organization", "channel", "status", "source_detail", "villa")
    search_fields = ("guest__full_name", "external_id")
    date_hierarchy = "check_in"
    inlines = [PaymentInline]

from django.urls import path

from apps.bookings.views import (
    BookingRemoveView,
    BookingRescheduleView,
    BookingSearchSuggestionsView,
    CalendarView,
    ReservationAvailabilityView,
    ReservationCreateView,
)

app_name = "bookings"

urlpatterns = [
    # Calendar is the main dashboard landing view, so it lives at the root
    # ("/calendar/") rather than under "/bookings/".
    path("calendar/", CalendarView.as_view(), name="calendar"),
    path("calendar/search/", BookingSearchSuggestionsView.as_view(), name="calendar_search"),
    path("bookings/add/", ReservationCreateView.as_view(), name="add"),
    path("bookings/add/availability/", ReservationAvailabilityView.as_view(), name="reservation_availability"),
    path("bookings/<int:pk>/remove/", BookingRemoveView.as_view(), name="remove"),
    path("bookings/<int:pk>/reschedule/", BookingRescheduleView.as_view(), name="reschedule"),
    # path("", views.BookingListView.as_view(), name="list"),
    # path("<uuid:reference>/", views.BookingDetailView.as_view(), name="detail"),
]

from django.urls import path

from apps.bookings.views import (
    BookingRemoveView,
    BookingRescheduleView,
    CalendarView,
    ReservationAvailabilityView,
    ReservationCreateView,
)

app_name = "bookings"

urlpatterns = [
    path("calendar/", CalendarView.as_view(), name="calendar"),
    path("add/", ReservationCreateView.as_view(), name="add"),
    path("add/availability/", ReservationAvailabilityView.as_view(), name="reservation_availability"),
    path("<int:pk>/remove/", BookingRemoveView.as_view(), name="remove"),
    path("<int:pk>/reschedule/", BookingRescheduleView.as_view(), name="reschedule"),
    # path("", views.BookingListView.as_view(), name="list"),
    # path("<uuid:reference>/", views.BookingDetailView.as_view(), name="detail"),
]

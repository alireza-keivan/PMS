from django.urls import path  # noqa: F401  - used once the views below are enabled

app_name = "bookings"

urlpatterns: list = [
    # path("", views.BookingListView.as_view(), name="list"),
    # path("calendar/", views.CalendarView.as_view(), name="calendar"),   # vis-timeline
    # path("<uuid:reference>/", views.BookingDetailView.as_view(), name="detail"),
]

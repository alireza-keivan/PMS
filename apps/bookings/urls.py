from django.urls import path
from django.utils.translation import gettext_lazy as _

from apps.bookings.views import CalendarView
from apps.core.views import ComingSoonView

app_name = "bookings"

urlpatterns = [
    path("calendar/", CalendarView.as_view(), name="calendar"),
    path("add/", ComingSoonView.as_view(extra_context={"title": _("New booking")}), name="add"),
    # path("", views.BookingListView.as_view(), name="list"),
    # path("<uuid:reference>/", views.BookingDetailView.as_view(), name="detail"),
]

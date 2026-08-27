from django.urls import path
from django.utils.translation import gettext_lazy as _

from apps.core.views import ComingSoonView

app_name = "bookings"

urlpatterns = [
    path("calendar/", ComingSoonView.as_view(extra_context={"title": _("Bookings")}), name="calendar"),
    # path("", views.BookingListView.as_view(), name="list"),
    # path("<uuid:reference>/", views.BookingDetailView.as_view(), name="detail"),
]

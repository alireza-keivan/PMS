from django.urls import path

from apps.guests.views import GuestDetailView, GuestRequestListView, GuestRequestStatusView

app_name = "guests"

urlpatterns = [
    path("requests/", GuestRequestListView.as_view(), name="requests"),
    path("requests/<int:pk>/status/", GuestRequestStatusView.as_view(), name="request_status"),
    # Last: a bare <int:pk> would otherwise swallow nothing here, but keeping
    # the literal paths first makes the ordering rule obvious for the next one.
    path("<int:pk>/", GuestDetailView.as_view(), name="detail"),
]

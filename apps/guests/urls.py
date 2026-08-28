from django.urls import path

from apps.guests.views import GuestDetailView, ReservationListView

app_name = "guests"

urlpatterns = [
    path("", ReservationListView.as_view(), name="list"),
    path("<int:pk>/", GuestDetailView.as_view(), name="detail"),
]

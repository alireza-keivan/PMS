from django.urls import path

from apps.guests.views import GuestDetailView

app_name = "guests"

urlpatterns = [
    path("<int:pk>/", GuestDetailView.as_view(), name="detail"),
]

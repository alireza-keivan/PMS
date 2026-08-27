from django.urls import path

from apps.reporting.views import DashboardView

app_name = "reporting"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
]

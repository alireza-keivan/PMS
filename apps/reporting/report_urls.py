"""The /reporting page lives at the site root, not under /today/, so it gets
its own url module rather than sharing the dashboard's prefix."""

from django.urls import path

from apps.reporting.views import ReportsView

app_name = "reports"

urlpatterns = [
    path("", ReportsView.as_view(), name="index"),
]

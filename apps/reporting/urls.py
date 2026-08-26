from django.urls import path  # noqa: F401  - used once the views below are enabled

app_name = "reporting"

urlpatterns: list = [
    # path("", views.DashboardView.as_view(), name="dashboard"),   # owner view
    # path("today/", views.TodayView.as_view(), name="today"),     # daily staff view
]

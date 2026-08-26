from django.urls import path  # noqa: F401  - used once the views below are enabled

app_name = "guests"

# Staff-facing views: guest list, one guest's history, activity analysis.
urlpatterns: list = [
    # path("", views.GuestListView.as_view(), name="list"),
    # path("<int:pk>/", views.GuestDetailView.as_view(), name="detail"),
]

from django.urls import path  # noqa: F401  - used once the views below are enabled

"""Guest-facing portal. Reached by signed link only - never session auth.

Mounted at /stay/<token>/. Every view must resolve the token to a booking and
scope strictly to it.
"""


app_name = "portal"

urlpatterns: list = [
    # path("<str:token>/", views.PortalHomeView.as_view(), name="home"),
    # path("<str:token>/request/", views.RequestCreateView.as_view(), name="request"),
    # path("<str:token>/experiences/", views.ExperienceListView.as_view(), name="experiences"),
    # path("<str:token>/feedback/", views.FeedbackView.as_view(), name="feedback"),
]

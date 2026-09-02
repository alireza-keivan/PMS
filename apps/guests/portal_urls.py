"""Guest-facing portal. Reached by signed link only - never session auth.

Mounted at /stay/<token>/. Every view must resolve the token to a booking and
scope strictly to it.
"""

from django.urls import path

from apps.guests import portal_views

app_name = "portal"

urlpatterns = [
    path("<str:token>/", portal_views.PortalHomeView.as_view(), name="home"),
    path("<str:token>/request/", portal_views.RequestCreateView.as_view(), name="request"),
    # Build order step 5, not built yet:
    # path("<str:token>/experiences/", views.ExperienceListView.as_view(), name="experiences"),
    # path("<str:token>/feedback/", views.FeedbackView.as_view(), name="feedback"),
]

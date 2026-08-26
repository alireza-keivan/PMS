from django.urls import path  # noqa: F401  - used once the views below are enabled

"""Public, unauthenticated, SEO-indexed villa pages.

Server-rendered rather than a SPA precisely because these need to be crawlable
and fast on a phone over Indonesian mobile data.
"""


app_name = "marketing"

urlpatterns: list = [
    # path("<slug:org>/<slug:villa>/", views.VillaPageView.as_view(), name="villa_page"),
    # path("<slug:org>/<slug:villa>/book/", views.DirectBookingView.as_view(), name="book"),
]

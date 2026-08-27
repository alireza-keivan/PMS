"""Public, unauthenticated, SEO-indexed villa pages.

Server-rendered rather than a SPA precisely because these need to be crawlable
and fast on a phone over Indonesian mobile data. Staff-facing marketing
management (rate parity, experiences) lives in apps.marketing.staff_urls
instead - keeping the two apart means a bug in the public site can never
accidentally expose an authenticated-only view, and vice versa.
"""

from django.urls import path  # noqa: F401  - used once the views below are enabled

app_name = "marketing"

urlpatterns: list = [
    # path("<slug:org>/<slug:villa>/", views.VillaPageView.as_view(), name="villa_page"),
    # path("<slug:org>/<slug:villa>/book/", views.DirectBookingView.as_view(), name="book"),
]

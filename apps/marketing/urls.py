"""Public, unauthenticated, SEO-indexed villa pages.

Server-rendered rather than a SPA precisely because these need to be crawlable
and fast on a phone over Indonesian mobile data. Staff-facing marketing
management (rate parity, experiences) lives in apps.marketing.staff_urls
instead - keeping the two apart means a bug in the public site can never
accidentally expose an authenticated-only view, and vice versa.
"""

from django.urls import path

from apps.marketing import views

app_name = "marketing"

# Both slugs together, always: the org slug is what scopes the lookup to one
# operator, since there is no signed-in user out here to do it. See
# apps.marketing.views.published_villa_or_404.
urlpatterns = [
    path("<slug:org>/<slug:villa>/", views.VillaPageView.as_view(), name="villa_page"),
    path("<slug:org>/<slug:villa>/book/", views.DirectBookingView.as_view(), name="book"),
]

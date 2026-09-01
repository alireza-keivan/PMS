"""Root URL configuration.

Three distinct audiences, deliberately kept apart:
  - /            staff + owner dashboard (session auth required)
  - /stay/       guest portal (signed link, no account)
  - /villa/      public mini villa sites (no auth, SEO-indexed)
  - /api/        webhooks and machine callers (Django Ninja, no session auth)
  - /auth/       the Google sign-in round trip (allauth)
"""

from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from config.api import api

# Not language-prefixed: machines and the admin do not need a locale in the URL.
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    # Not language-prefixed on purpose: Google is configured with one exact
    # redirect address, and anything inside i18n_patterns changes shape under
    # /id/. The callback is /auth/google/login/callback/ in every language.
    path("auth/", include("allauth.urls")),
]

# Language-prefixed (/en/..., /id/...) so both locales are linkable and indexable.
urlpatterns += i18n_patterns(
    # The site root has no page of its own; the calendar is the dashboard
    # landing view, and it handles the login redirect itself.
    path("", RedirectView.as_view(pattern_name="bookings:calendar", permanent=False), name="home"),
    path("", include("apps.bookings.urls", namespace="bookings")),
    path("today/", include("apps.reporting.urls", namespace="reporting")),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("villas/", include("apps.villas.urls", namespace="villas")),
    path("guests/", include("apps.guests.urls", namespace="guests")),
    path("compliance/", include("apps.compliance.urls", namespace="compliance")),
    path("messages/", include("apps.messaging.urls", namespace="messaging")),
    path("team/", include("apps.organizations.urls", namespace="organizations")),
    path("marketing/", include("apps.marketing.staff_urls", namespace="marketing_admin")),
    path("stay/", include("apps.guests.portal_urls", namespace="portal")),
    path("villa/", include("apps.marketing.urls", namespace="marketing")),
    prefix_default_language=False,
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

"""Root URL configuration.

Three distinct audiences, deliberately kept apart:
  - /            staff + owner dashboard (session auth required)
  - /stay/       guest portal (signed link, no account)
  - /villa/      public mini villa sites (no auth, SEO-indexed)
  - /api/        webhooks and machine callers (Django Ninja, no session auth)
"""

from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.api import api

# Not language-prefixed: machines and the admin do not need a locale in the URL.
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("i18n/", include("django.conf.urls.i18n")),
]

# Language-prefixed (/en/..., /id/...) so both locales are linkable and indexable.
urlpatterns += i18n_patterns(
    path("", include("apps.reporting.urls", namespace="reporting")),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("villas/", include("apps.villas.urls", namespace="villas")),
    path("bookings/", include("apps.bookings.urls", namespace="bookings")),
    path("compliance/", include("apps.compliance.urls", namespace="compliance")),
    path("guests/", include("apps.guests.urls", namespace="guests")),
    path("stay/", include("apps.guests.portal_urls", namespace="portal")),
    path("villa/", include("apps.marketing.urls", namespace="marketing")),
    prefix_default_language=False,
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

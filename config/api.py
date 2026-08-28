"""Django Ninja API root.

Two audiences share this namespace:
  - Webhooks and machine-to-machine callers (Beds24, WhatsApp, Stripe) -
    authenticate by shared secret or provider signature, never by session,
    and every endpoint must be idempotent - all three providers retry on
    non-2xx responses.
  - One session-authenticated dashboard endpoint (apps.bookings.api) that the
    booking calendar's own JS calls directly to refresh the visible date
    range, authenticated via the normal Django session cookie
    (ninja.security.django_auth). This is a deliberate, narrow exception to
    "never by session" - not a precedent for a general-purpose frontend REST
    API. Don't add further session-authenticated routes here without
    reconsidering whether they belong on this namespace at all.
"""

from ninja import NinjaAPI

from apps.bookings.api import router as bookings_router

api = NinjaAPI(
    title="Villa Dashboard API",
    version="1.0.0",
    docs_url=None,  # no public schema browser
    urls_namespace="api",
)

api.add_router("/bookings/", bookings_router)

# Further routers are registered as each integration lands - see the build
# order in CLAUDE.md. Step 1 is Beds24.
#
# from apps.sync.api import router as sync_router
# from apps.messaging.api import router as whatsapp_router
# api.add_router("/sync/", sync_router)
# api.add_router("/whatsapp/", whatsapp_router)

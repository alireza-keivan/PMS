"""Django Ninja API root - webhooks and machine-to-machine callers only.

This is deliberately not a general-purpose REST API for the frontend. The
dashboard is server-rendered with HTMX and talks to normal Django views; this
namespace exists for external systems that push data to us.

Every router here authenticates by shared secret or provider signature, never
by session, and every endpoint must be idempotent - all three providers retry
on non-2xx responses.
"""

from ninja import NinjaAPI

api = NinjaAPI(
    title="Villa Dashboard webhooks",
    version="1.0.0",
    docs_url=None,  # no public schema browser
    urls_namespace="api",
)

# Routers are registered as each integration lands - see the build order in
# CLAUDE.md. Step 1 is Beds24.
#
# from apps.sync.api import router as sync_router
# from apps.messaging.api import router as whatsapp_router
# api.add_router("/sync/", sync_router)
# api.add_router("/whatsapp/", whatsapp_router)

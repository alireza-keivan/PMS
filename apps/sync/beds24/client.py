"""Beds24 API v2 client.

Beds24 is the only route to Airbnb and Booking.com data for this project.
Neither offers API access to individual developers - only to approved
Connectivity Partners, which is not a programme open to us. Do not add direct
OTA integrations; see CLAUDE.md.

Auth: a long-lived refresh token is exchanged for a short-lived access token.
Cache the access token and refresh on 401 rather than requesting one per call.
"""

import httpx
from django.conf import settings


class Beds24Error(RuntimeError):
    pass


class Beds24Client:
    def __init__(self, refresh_token: str, base_url: str | None = None):
        self._refresh_token = refresh_token
        self._base_url = base_url or settings.BEDS24_API_BASE
        self._access_token: str | None = None

    async def _headers(self) -> dict[str, str]:
        if self._access_token is None:
            self._access_token = await self._fetch_access_token()
        return {"token": self._access_token, "Accept": "application/json"}

    async def _fetch_access_token(self) -> str:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=20) as client:
            response = await client.get(
                "/authentication/token", headers={"refreshToken": self._refresh_token}
            )
            if response.status_code != 200:
                raise Beds24Error(f"Token request failed: {response.status_code}")
            return response.json()["token"]

    async def get_bookings(self, *, modified_since: str | None = None) -> list[dict]:
        """Fetch bookings, optionally only those changed since a timestamp.

        Incremental pulls keep reconciliation cheap; a full pull is only needed
        on first connect.
        """
        params = {"modifiedSince": modified_since} if modified_since else {}
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            response = await client.get("/bookings", params=params, headers=await self._headers())
            if response.status_code != 200:
                raise Beds24Error(f"Booking fetch failed: {response.status_code}")
            return response.json().get("data", [])

    # Writing to live availability is deliberately not implemented. Yield rules
    # are parked in the backlog, and a bug here would cause the exact
    # double-booking this product exists to prevent. See CLAUDE.md rule 5.

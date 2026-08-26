"""iCal feed import - the free basic tier.

What this can do: block out dates that are already taken.
What it cannot do: name the guest, report the price, or carry a message.

OTAs typically refresh these feeds every few hours, so the data is genuinely
stale by design. Bookings created here are marked DATES_ONLY so the interface
never describes them as complete or current. See CLAUDE.md.
"""

import httpx
from icalendar import Calendar


async def fetch_events(ical_url: str) -> list[dict]:
    """Return the booked date ranges in a feed.

    UID is the OTA's own identifier and is stable across refreshes - it is what
    makes repeat imports idempotent rather than duplicating every run.
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(ical_url)
        response.raise_for_status()

    calendar = Calendar.from_ical(response.content)
    events = []
    for component in calendar.walk("VEVENT"):
        events.append(
            {
                "uid": str(component.get("UID", "")),
                "start": component.decoded("DTSTART"),
                "end": component.decoded("DTEND"),
                "summary": str(component.get("SUMMARY", "")),
            }
        )
    return events

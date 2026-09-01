"""Calendar query and business logic.

Two presenters over one query:
  - build_calendar_rows() backs the server-rendered grid (apps.bookings.views).
    The grid is plain HTML + CSS grid, not a JS timeline widget - see the
    design handoff in New UI mockups/design_handoff_villa_dashboard/README.md.
  - build_calendar_data() backs the JSON endpoint (apps.bookings.api).
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Max, Q, Sum
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.text import slugify
from django.utils.translation import gettext, ngettext
from django.utils.translation import gettext_lazy as _

from apps.bookings.models import Booking, BookingPayment
from apps.organizations.permissions import can_see_money as _can_see_money
from apps.organizations.scoping import scoped_villas
from apps.villas.models import Room, RoomCategory

def _villa_abbreviation(name: str) -> str:
    """Short initials for narrow screens, e.g. "Bamboo Loft Canggu" -> "BLC"."""
    words = [w for w in name.split() if w]
    if len(words) >= 2:
        return "".join(w[0] for w in words[:4]).upper()
    return name[:3].upper()


CALENDAR_STATUS_LABELS = {
    "confirmed": _("Confirmed"),
    "checked_in": _("Checked in"),
    "checked_out": _("Checked out"),
    "blocked": _("Not available"),
    "payment_incomplete": _("Payment incomplete"),
}


def _short_date(value) -> str:
    """"04 Aug" in English, "04 Agu" in Indonesian.

    Never strftime for anything a person reads: strftime takes its month names
    from the operating system's C locale, so it would say "Aug" even with the
    dashboard switched to Bahasa Indonesia. Django's own formatter routes the
    "M" specifier through the translated month table instead.
    """
    return formats.date_format(value, "d M")


def _money(amount) -> str:
    """A figure with the active locale's own grouping - 1,500,000 or 1.500.000."""
    return formats.number_format(amount, force_grouping=True)


def calendar_status(booking: Booking, today, amount_owed: Decimal) -> str:
    """One color per bar. Money owed always wins over stay stage - see the
    calendar plan's decision on color priority. Blocked bookings never carry
    payments (iCal blocks have no guest, no price), so they're never in the
    running for "payment incomplete" in the first place.
    """
    if booking.status == Booking.Status.BLOCKED:
        return "blocked"
    if amount_owed and amount_owed > 0:
        return "payment_incomplete"
    if today < booking.check_in:
        return "confirmed"
    if today < booking.check_out:
        return "checked_in"
    return "checked_out"


def payment_summary_by_booking(org, booking_ids: list) -> dict:
    """{booking_id: {"total_amount": Decimal, "amount_owed": Decimal, "currency": str}}

    A booking with no BookingPayment rows (every calendar-only/iCal booking)
    is simply absent from the dict - callers default owed to 0 and total/
    currency to None rather than treating a missing row as an error.
    """
    if not booking_ids:
        return {}
    rows = (
        BookingPayment.objects.filter(organization=org, booking_id__in=booking_ids)
        .values("booking_id")
        .annotate(
            total_amount=Sum("amount", filter=~Q(kind=BookingPayment.Kind.REFUND)),
            amount_owed=Sum("amount", filter=Q(is_outstanding=True)),
            currency=Max("currency"),
        )
    )
    return {row["booking_id"]: row for row in rows}


def _calendar_query(request, start, days, q):
    """The one query behind both presenters: which villas/rooms are visible,
    and which bookings fall inside the window.
    """
    org = request.organization
    range_end = start + timedelta(days=days)

    villas, membership = scoped_villas(request)

    if q:
        q_lower = q.lower()
        name_matched_ids = {v.id for v in villas if q_lower in v.name.lower()}
        guest_matched_ids = set(
            Booking.objects.filter(
                organization=org, villa_id__in=[v.id for v in villas],
                check_in__lt=range_end, check_out__gt=start,
                guest__full_name__icontains=q,
            ).exclude(status=Booking.Status.CANCELLED).values_list("villa_id", flat=True)
        )
        villas = [v for v in villas if v.id in (name_matched_ids | guest_matched_ids)]

    bookings = list(
        Booking.objects.filter(
            organization=org, villa_id__in=[v.id for v in villas],
            check_in__lt=range_end, check_out__gt=start,
        ).exclude(status=Booking.Status.CANCELLED).select_related("villa", "guest", "room")
    )
    payments = payment_summary_by_booking(org, [b.id for b in bookings])
    rooms_by_villa = _rooms_by_villa([v.id for v in villas])
    return villas, bookings, payments, rooms_by_villa, membership


def build_calendar_data(request, start, days, q) -> dict:
    today = timezone.localdate()
    villas, bookings, payments, rooms_by_villa, _membership = _calendar_query(request, start, days, q)

    groups = _build_groups(villas, bookings, rooms_by_villa)
    can_see_money = _can_see_money(request.user)
    items = [
        _build_item(b, today, payments.get(b.id, {}), can_see_money, rooms_by_villa)
        for b in bookings
    ]
    return {"groups": groups, "items": items}


# One swatch colour per villa, cycled - purely decorative, so it's derived
# from position rather than stored on the model. Values are the design
# system's accent-300 / accent-2-300 / neutral-300 steps.
VILLA_SWATCHES = ["#ffc6a5", "#ccdbb2", "#dcd3c4"]

# Room types are named per villa now, so a colour can't be looked up by name.
# Cycled by the type's position within its own villa instead, which keeps a
# villa's types visually distinct and stable as it is renamed.
#
# The type used to be printed as a text tag beside the room name, but that
# column is only ~108px wide on a phone and the tag squeezed the room name
# down to a few letters. The type is shown as colour alone now - a stripe down
# the left edge of the name cell, the cell itself keeping the same background
# as every other room - so the name gets the whole column back. The type's
# name still rides along as the cell's tooltip and aria label, so the words
# aren't lost for anyone who needs them.
ROOM_CATEGORY_STRIPES = ["#c0b6a5", "#d67f48", "#8fa073"]  # sand / terracotta / sage


def _category_style(room) -> str:
    index = room.category.sort_order if room.category_id is not None else 0
    stripe = ROOM_CATEGORY_STRIPES[index % len(ROOM_CATEGORY_STRIPES)]
    return f"box-shadow:inset 3px 0 0 {stripe};"

# Bar fills, straight from the design handoff's status table. Blocked is a
# hatch rather than a flat fill so "not available" never reads as a real stay.
STATUS_BAR_STYLE = {
    "confirmed": "background:#e1eecc;color:#3d472b;",
    "checked_in": "background:#8fa073;color:#f5ead8;",
    "checked_out": "background:#eee7db;color:#82796a;",
    "blocked": (
        "background:repeating-linear-gradient(135deg,#dcd3c4 0 6px,#eee7db 6px 12px);"
        "color:#645c50;border:1px dashed #a19786;"
    ),
    "payment_incomplete": "background:#ffe1d0;color:#643312;border:1px solid #d67f48;",
}


def build_calendar_rows(request, start, days, q) -> dict:
    """The server-rendered grid: a list of day columns, and a flat list of
    rows (area header / villa header / room) the template walks in order.
    Flat rather than nested so the template stays a single simple loop.
    """
    today = timezone.localdate()
    villas, bookings, payments, rooms_by_villa, _membership = _calendar_query(request, start, days, q)
    categories_by_villa = _room_categories_by_villa([v.id for v in villas])
    can_see_money = _can_see_money(request.user)

    day_columns = [
        {
            "date": start + timedelta(days=i),
            "is_today": start + timedelta(days=i) == today,
        }
        for i in range(days)
    ]

    bookings_by_room: dict = {}
    for booking in bookings:
        bookings_by_room.setdefault(booking.room_id, []).append(booking)

    # Area buckets, alphabetical, with the catch-all "Other" pinned last.
    buckets: dict = {}
    for villa in villas:
        key = slugify(villa.area) if villa.area else "other"
        buckets.setdefault(key, {"label": villa.area or str(_("Other")), "villas": []})
        buckets[key]["villas"].append(villa)
    ordered_areas = sorted(buckets.items(), key=lambda kv: (kv[0] == "other", kv[1]["label"]))

    rows = []
    swatch_index = 0
    for _area_key, bucket in ordered_areas:
        rows.append({"kind": "area", "label": bucket["label"]})
        for villa in bucket["villas"]:
            rooms = rooms_by_villa.get(villa.id, [])
            rows.append({
                "kind": "villa",
                "id": villa.id,
                "name": villa.name,
                "short_name": _villa_abbreviation(villa.name),
                "slug": villa.slug,
                "swatch": VILLA_SWATCHES[swatch_index % len(VILLA_SWATCHES)],
                "room_count": len(rooms),
            })
            swatch_index += 1
            for room in rooms:
                rows.append({
                    "kind": "room",
                    "id": room.id,
                    "villa_id": villa.id,
                    "villa_slug": villa.slug,
                    "name": room.name,
                    "category_label": room.category.name if room.category_id else "",
                    "category_style": _category_style(room),
                    "bars": [
                        _build_bar(b, today, payments.get(b.id, {}), can_see_money, start, days)
                        for b in bookings_by_room.get(room.id, [])
                    ],
                })
            rows.append({
                "kind": "add_room",
                "villa_id": villa.id,
                "villa_slug": villa.slug,
                "categories": categories_by_villa.get(villa.id, []),
            })

    return {"day_columns": day_columns, "rows": rows}


def _build_bar(booking, today, payment, can_see_money, start, days) -> dict:
    """One booking bar, positioned as a percentage of the visible window.

    A stay that starts before the window (or ends after it) is clamped to the
    edge rather than dropped, so a guest who is mid-stay on the first visible
    day still shows up.
    """
    status = calendar_status(booking, today, payment.get("amount_owed") or Decimal("0"))
    label = booking.guest.full_name if booking.has_guest_details else gettext("Booked")

    start_offset = max(0, (booking.check_in - start).days)
    end_offset = min(days, (booking.check_out - start).days)
    span = max(1, end_offset - start_offset)

    left = (start_offset / days) * 100
    width = (span / days) * 100

    bar = {
        "id": booking.id,
        "room_id": booking.room_id,
        # Real (unclamped) dates, for the drag-to-reschedule flow - start_offset/
        # end_offset above are clamped to the visible window and only ever meant
        # for positioning, not for telling the client what the booking actually is.
        "check_in_iso": booking.check_in.isoformat(),
        "check_out_iso": booking.check_out.isoformat(),
        "label": label,
        "status": status,
        "status_display": str(CALENDAR_STATUS_LABELS[status]),
        "style": (
            f"left:calc({left:.4f}% + 3px);width:calc({width:.4f}% - 6px);"
            + STATUS_BAR_STYLE[status]
        ),
        "villa_name": booking.villa.name,
        "room_name": booking.room.name if booking.room_id else "",
        "date_range": f"{_short_date(booking.check_in)} – {_short_date(booking.check_out)}",
        "nights": booking.nights,
        "guest_count": booking.guest_count,
        "channel_display": booking.get_channel_display(),
        "has_guest_details": booking.has_guest_details,
        "guest_url": (
            reverse("guests:detail", args=[booking.guest_id])
            if booking.has_guest_details and booking.guest_id
            else ""
        ),
        "can_see_money": can_see_money,
        "amount_owed": None,
        "currency": None,
    }
    if can_see_money:
        owed = payment.get("amount_owed")
        bar["amount_owed"] = _money(owed) if owed is not None else None
        bar["currency"] = payment.get("currency")
    return bar


def find_available_room(room_category: RoomCategory, check_in, check_out):
    """The first of this room type's rooms that's free for the given dates,
    and, if none are, the soonest date one of them frees up.

    Used by the Add Reservation form both for the live availability check
    (apps.bookings.views.ReservationAvailabilityView) and to actually assign a
    room on save - re-run server-side at submit time rather than trusting
    whatever the live check last showed the client, same principle as
    BookingRescheduleView's overlap check.

    Returns (room, None) if a room is free, or (None, next_free_date) if every
    room of this type is booked - next_free_date is the earliest check-out
    among the bookings in the way, i.e. the soonest any of them opens up (not
    a guarantee it stays open past that date - just where to look next).
    """
    rooms = list(room_category.rooms.filter(is_active=True).order_by("id"))
    overlapping = list(
        Booking.objects.filter(
            organization=room_category.organization_id,
            room_id__in=[r.id for r in rooms],
            check_in__lt=check_out, check_out__gt=check_in,
        ).exclude(status=Booking.Status.CANCELLED).only("room_id", "check_out")
    )
    booked_room_ids = {b.room_id for b in overlapping}
    for room in rooms:
        if room.id not in booked_room_ids:
            return room, None
    next_free_date = min((b.check_out for b in overlapping), default=None)
    return None, next_free_date


def _rooms_by_villa(villa_ids: list) -> dict:
    """{villa_id: [Room, ...]} for every active room across the given villas.
    A villa absent from this dict has no rooms defined - the common case
    today - and keeps rendering as one flat row, same as before rooms existed.

    Room types come along on the same query: each room row draws its type as a
    tag, so fetching them lazily would be one extra query per room.
    """
    buckets: dict = {}
    rooms = (
        Room.objects.filter(villa_id__in=villa_ids, is_active=True)
        .select_related("category").order_by("category__sort_order", "id")
    )
    for room in rooms:
        buckets.setdefault(room.villa_id, []).append(room)
    return buckets


def _room_categories_by_villa(villa_ids: list) -> dict:
    """{villa_id: [category dict, ...]} for the calendar's "+ Add room" card,
    which needs to know whether a villa has more than one room type before
    deciding whether to ask which one - and, if it asks, what to show about
    each type once picked.
    """
    buckets: dict = {}
    categories = (
        RoomCategory.objects.filter(villa_id__in=villa_ids)
        .prefetch_related("amenities").order_by("sort_order", "name")
    )
    for category in categories:
        buckets.setdefault(category.villa_id, []).append({
            "id": category.id,
            "name": category.name,
            "room_count": category.room_count,
            "max_guests": category.max_guests,
            "size_sqm": category.size_sqm,
            "nightly_rate": category.nightly_rate,
            "amenity_names": [amenity.name_en for amenity in category.amenities.all()],
        })
    return buckets


def _build_groups(villas: list, bookings: list, rooms_by_villa: dict) -> list:
    buckets = {}
    for v in villas:
        area_key = slugify(v.area) if v.area else "other"
        bucket = buckets.setdefault(area_key, {"label": v.area or str(_("Other")), "villa_ids": []})
        bucket["villa_ids"].append(f"villa-{v.id}")

    ordered = sorted(buckets.items(), key=lambda kv: (kv[0] == "other", kv[1]["label"]))

    groups = []
    for area_key, bucket in ordered:
        group_id = f"area-{area_key}"
        groups.append({"id": group_id, "content": bucket["label"], "nestedGroups": bucket["villa_ids"]})

    # Villa ids and room ids are different tables' autoincrement PKs, so
    # group ids are namespaced ("villa-<id>" / "room-<id>") to avoid a
    # numeric collision now that both can appear as leaf group ids.
    villas_needing_unassigned = {
        b.villa_id for b in bookings if b.room_id is None and b.villa_id in rooms_by_villa
    }

    for v in villas:
        rooms = rooms_by_villa.get(v.id, [])
        if not rooms:
            groups.append({"id": f"villa-{v.id}", "content": v.name})
            continue

        room_group_ids = [f"room-{r.id}" for r in rooms]
        if v.id in villas_needing_unassigned:
            room_group_ids.append(f"room-none-{v.id}")

        groups.append({"id": f"villa-{v.id}", "content": v.name, "nestedGroups": room_group_ids})
        for r in rooms:
            groups.append({"id": f"room-{r.id}", "content": r.name})
        if v.id in villas_needing_unassigned:
            groups.append({"id": f"room-none-{v.id}", "content": str(_("Unassigned"))})

    return groups


def _build_item(booking: Booking, today, payment: dict, can_see_money: bool, rooms_by_villa: dict) -> dict:
    status = calendar_status(booking, today, payment.get("amount_owed") or Decimal("0"))
    content = booking.guest.full_name if booking.has_guest_details else gettext("Booked")

    class_names = f"cal-status-{status}"
    if not booking.has_guest_details:
        class_names += " cal-no-detail"

    date_range = gettext("%(start)s – %(end)s") % {
        "start": _short_date(booking.check_in),
        "end": _short_date(booking.check_out),
    }
    nights_label = ngettext("%(n)s night", "%(n)s nights", booking.nights) % {"n": booking.nights}
    title = "<br>".join([
        content,
        booking.villa.name,
        f"{date_range} ({nights_label})",
        booking.get_channel_display(),
    ])

    if booking.room_id:
        group = f"room-{booking.room_id}"
    elif rooms_by_villa.get(booking.villa_id):
        group = f"room-none-{booking.villa_id}"
    else:
        group = f"villa-{booking.villa_id}"

    item = {
        "id": booking.id,
        "group": group,
        "start": booking.check_in.isoformat(),
        "end": booking.check_out.isoformat(),
        "content": content,
        "className": class_names,
        "title": title,
        "type": "range",
        "guest_count": booking.guest_count,
        "channel_display": booking.get_channel_display(),
        "status_display": str(CALENDAR_STATUS_LABELS[status]),
        "has_guest_details": booking.has_guest_details,
        "can_see_money": can_see_money,
        "reference": str(booking.reference),
        "villa_name": booking.villa.name,
        "room_display": booking.room.name if booking.room_id else None,
        "total_amount": None,
        "amount_owed": None,
        "currency": None,
    }
    if can_see_money:
        total = payment.get("total_amount")
        owed = payment.get("amount_owed")
        item["total_amount"] = str(total) if total is not None else None
        item["amount_owed"] = str(owed) if owed is not None else None
        item["currency"] = payment.get("currency")
    return item

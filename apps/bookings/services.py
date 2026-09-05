"""Calendar query and business logic.

Two presenters over one query:
  - build_calendar_rows() backs the server-rendered grid (apps.bookings.views).
    The grid is plain HTML + CSS grid, not a JS timeline widget - see the
    design handoff in New UI mockups/design_handoff_villa_dashboard/README.md.
  - build_calendar_data() backs the JSON endpoint (apps.bookings.api).
"""

import logging
from collections import namedtuple
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

logger = logging.getLogger(__name__)

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
# Every status now carries its own border too - with bars able to sit flush
# against each other at a same-day changeover (see _bar_shape_style), a
# border is what keeps two touching bars reading as two separate bookings
# instead of one continuous blob.
STATUS_BAR_STYLE = {
    "confirmed": "background:#e1eecc;color:#3d472b;border:1px solid #b3cb8c;",
    "checked_in": "background:#8fa073;color:#f5ead8;border:1px solid #6d7d55;",
    "checked_out": "background:#eee7db;color:#82796a;border:1px solid #cfc4b0;",
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

    # Whether a room can actually be removed - RoomDeleteView blocks on ANY
    # booking ever made against it (even cancelled or long past), since the
    # room FK is PROTECT. bookings_by_room above only covers this calendar's
    # visible date window, so that can't answer this - a separate all-time
    # existence check is needed to warn honestly in the remove-room dialog
    # instead of promising a removal the server will then refuse.
    all_room_ids = [room.id for rooms in rooms_by_villa.values() for room in rooms]
    rooms_with_bookings = set(
        Booking.objects.filter(room_id__in=all_room_ids).values_list("room_id", flat=True).distinct()
    )

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
                room_bookings = sorted(bookings_by_room.get(room.id, []), key=lambda b: b.check_in)
                # Same-day changeovers (one guest's morning check-out is another's
                # noon check-in) are common and, drawn as two bars with a plain
                # vertical seam, read as if that day belongs to nobody or to
                # both at once. adjoins_next/adjoins_prev flag those touching
                # pairs so _build_bar can draw a diagonal seam through the
                # shared day instead - see the split-day sketch this was built
                # from.
                checkout_dates = {b.check_out for b in room_bookings}
                checkin_dates = {b.check_in for b in room_bookings}
                rows.append({
                    "kind": "room",
                    "id": room.id,
                    "villa_id": villa.id,
                    "villa_slug": villa.slug,
                    "name": room.name,
                    "category_label": room.category.name if room.category_id else "",
                    "category_style": _category_style(room),
                    "has_bookings": room.id in rooms_with_bookings,
                    "bars": [
                        _build_bar(
                            b, today, payments.get(b.id, {}), can_see_money, start, days,
                            adjoins_prev=b.check_in in checkout_dates,
                            adjoins_next=b.check_out in checkin_dates,
                        )
                        for b in room_bookings
                    ],
                })
            rows.append({
                "kind": "add_room",
                "villa_id": villa.id,
                "villa_slug": villa.slug,
                "categories": categories_by_villa.get(villa.id, []),
            })

    return {"day_columns": day_columns, "rows": rows}


def _bar_shape_style(left, width, adjoins_prev, adjoins_next) -> str:
    """left/width for the bar, with each free end capped as a half circle -
    the radius is larger than the bar is tall, so the cap reads as a full
    ")" / "(" curve rather than a slightly softened corner. The two corners
    on a side that touches a back-to-back booking are squared off instead,
    so the two bars butt flush against each other on that shared day rather
    than leaving a rounded notch of gap between them. A solid border (see
    STATUS_BAR_STYLE) is what actually shows "this day is shared" between
    two touching bars.

    An earlier version of this cut a quarter-circle notch out of the
    touching corner via clip-path, but a clip-path mask always renders with
    hard polygon facets - there's no way to blend it into the box's own
    border-radius curve - so the "rounded" corner ended up reading as a
    sharp diagonal cut instead. Plain border-radius has no such limit.
    """
    left_pad = 0 if adjoins_prev else 3
    right_pad = 0 if adjoins_next else 3
    radius = "999px"
    top_left = "0" if adjoins_prev else radius
    bottom_left = "0" if adjoins_prev else radius
    top_right = "0" if adjoins_next else radius
    bottom_right = "0" if adjoins_next else radius

    return (
        f"left:calc({left:.4f}% + {left_pad}px);"
        f"width:calc({width:.4f}% - {left_pad + right_pad}px);"
        f"border-radius:{top_left} {top_right} {bottom_right} {bottom_left};"
    )


def _build_bar(booking, today, payment, can_see_money, start, days, adjoins_prev=False, adjoins_next=False) -> dict:
    """One booking bar, positioned as a percentage of the visible window.

    A stay that starts before the window (or ends after it) is clamped to the
    edge rather than dropped, so a guest who is mid-stay on the first visible
    day still shows up.
    """
    status = calendar_status(booking, today, payment.get("amount_owed") or Decimal("0"))
    is_block = booking.status == Booking.Status.BLOCKED
    # A blocked range has no guest behind it by definition, so "Booked" would
    # be a small lie on the bar - it says the same thing the legend does.
    if booking.has_guest_details:
        label = booking.guest.full_name
    else:
        label = gettext("Not available") if is_block else gettext("Booked")

    start_offset = max(0, (booking.check_in - start).days)
    end_offset = min(days, (booking.check_out - start).days)
    span = max(1, end_offset - start_offset)

    left = (start_offset / days) * 100
    width = (span / days) * 100

    # Only notch the corner against a neighbour actually visible in this
    # window - a booking clamped to the window edge isn't really touching
    # anything on screen.
    shape_adjoins_prev = adjoins_prev and start_offset > 0
    shape_adjoins_next = adjoins_next and end_offset < days

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
            _bar_shape_style(left, width, shape_adjoins_prev, shape_adjoins_next)
            + STATUS_BAR_STYLE[status]
        ),
        "villa_name": booking.villa.name,
        "room_name": booking.room.name if booking.room_id else "",
        "date_range": f"{_short_date(booking.check_in)} – {_short_date(booking.check_out)}",
        "nights": booking.nights,
        "guest_count": booking.guest_count,
        "channel_display": booking.get_channel_display(),
        "has_guest_details": booking.has_guest_details,
        "is_block": is_block,
        # Only ever staff-written text (notes on a blocked range, e.g. from an
        # imported iCal feed), never anything a guest typed.
        "reason": booking.notes if is_block else "",
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


# A booking we may pick up and put in a different room of the same type, as
# a plain tuple so the packer never touches the database while it thinks.
# `booking_id` is None for the stay being asked about, which isn't saved yet.
_Stay = namedtuple("_Stay", "booking_id room_id check_in check_out movable")


def _overlaps(a: _Stay, b: _Stay) -> bool:
    """True when two stays want the same room on the same night.

    Check-out day is not a night: a stay ending on the 3rd and one starting
    on the 3rd do not clash, which is exactly the case that makes the
    repacking below worth doing at all.
    """
    return a.check_in < b.check_out and a.check_out > b.check_in


def _pack(stays: list, room_ids: list, prefer_current: bool) -> dict:
    """Fit every stay into a room, or give up. Returns {stay_index: room_id}
    or {} if some stay had nowhere to go.

    First-fit by check-in date. On a set of date ranges this is the textbook
    optimal answer when everything is free to move - it never needs more
    rooms than the busiest single night needs - which is why the second pass
    below drops `prefer_current` and simply retries.

    With `prefer_current` on, a stay stays where it already is whenever that
    room still works. That is what keeps the number of guests told "you're in
    a different room now" as small as it can be, at the cost of the optimality
    guarantee - hence the two passes.
    """
    placed = {room_id: [] for room_id in room_ids}
    assignment = {}

    order = sorted(range(len(stays)), key=lambda i: (stays[i].check_in, stays[i].check_out))
    for index in order:
        stay = stays[index]

        # A stay we're not allowed to move has exactly one candidate room.
        if not stay.movable:
            candidates = [stay.room_id]
        elif prefer_current and stay.room_id in placed:
            candidates = [stay.room_id] + [r for r in room_ids if r != stay.room_id]
        else:
            candidates = room_ids

        for room_id in candidates:
            if room_id not in placed:
                continue
            if any(_overlaps(stay, other) for other in placed[room_id]):
                continue
            placed[room_id].append(stay)
            assignment[index] = room_id
            break
        else:
            return {}

    return assignment


def plan_room_moves(room_category: RoomCategory, check_in, check_out, today=None):
    """Work out whether shuffling this room type's upcoming bookings would
    make space for a stay from `check_in` to `check_out`.

    The problem this solves: three rooms of one type, booked 1-3 Sep, 3-5 Sep
    and 5-7 Sep, one room each. Every room is busy at some point in that week,
    so a guest asking for 1-7 Sep is turned away - even though the three short
    stays would all fit in a single room and leave the other two completely
    empty. This slides them together and hands back the room that frees up.

    Only ever looks at rooms of this one room type, never at the villa's other
    types - a guest who booked a Deluxe is not moved into a Standard.

    What it will not move:
      - a stay that has already started or is over: someone in the room
        tonight keeps their room number
      - a cancelled booking (it isn't occupying anything to begin with)
      - anything in a room that has been switched off

    Returns (room, moves): the room the new stay can have, and the list of
    (booking_id, from_room_id, to_room_id) that has to happen first - possibly
    empty, if it fits without moving anyone. Returns (None, []) when even a
    full reshuffle can't make it fit.

    Plans only - it writes nothing. apply_room_moves() does that, inside the
    same transaction that saves the booking.
    """
    today = today or timezone.localdate()

    rooms = list(room_category.rooms.filter(is_active=True).order_by("id"))
    room_ids = [room.id for room in rooms]
    if not room_ids:
        return None, []

    # Everything still ahead of us in these rooms. Stays already finished
    # can't be in the way of a future one, so they never enter the packing.
    bookings = (
        Booking.objects.filter(
            organization=room_category.organization_id,
            room_id__in=room_ids,
            check_out__gt=min(check_in, today),
        )
        .exclude(status=Booking.Status.CANCELLED)
        .only("id", "room_id", "check_in", "check_out")
    )

    stays = [
        _Stay(b.id, b.room_id, b.check_in, b.check_out, movable=b.check_in > today)
        for b in bookings
    ]
    wanted = len(stays)  # index of the new stay, added last
    stays.append(_Stay(None, None, check_in, check_out, movable=True))

    assignment = _pack(stays, room_ids, prefer_current=True)
    if not assignment:
        assignment = _pack(stays, room_ids, prefer_current=False)
    if not assignment:
        return None, []

    moves = [
        (stay.booking_id, stay.room_id, assignment[index])
        for index, stay in enumerate(stays)
        if stay.booking_id is not None and assignment[index] != stay.room_id
    ]
    room_by_id = {room.id: room for room in rooms}
    return room_by_id[assignment[wanted]], moves


def apply_room_moves(moves: list) -> None:
    """Write out a plan from plan_room_moves(). Call inside the transaction
    that saves the booking the moves were planned for - half a shuffle is
    worse than none, and the plan is only correct alongside that new booking.
    """
    for booking_id, from_room_id, to_room_id in moves:
        Booking.objects.filter(pk=booking_id).update(room_id=to_room_id)
        logger.info(
            "Booking %s moved from room %s to room %s to free up space",
            booking_id, from_room_id, to_room_id,
        )


def find_available_room(room_category: RoomCategory, check_in, check_out):
    """The room this room type can give a stay over the given dates, and what
    it would take to give it.

    Returns (room, next_free_date, moves):
      - a room is free right now            -> (room, None, [])
      - a room frees up by moving others    -> (room, None, [move, ...])
      - the type really is full             -> (None, next_free_date, [])

    `next_free_date` is the earliest check-out among the bookings in the way,
    i.e. the soonest any of them opens up - not a promise it stays open past
    that date, just where to look next.

    `moves` is only ever non-empty when the villa's manager has switched
    "move upcoming bookings between rooms" on for that villa
    (Villa.auto_reassign_rooms) - see plan_room_moves for the rules it plays
    by. The caller must pass the list to apply_room_moves() in the same
    transaction that saves the booking; anything only previewing availability
    can ignore it.

    Used by the Add Reservation form both for the live availability check
    (apps.bookings.views.ReservationAvailabilityView) and to actually assign a
    room on save - re-run server-side at submit time rather than trusting
    whatever the live check last showed the client, same principle as
    BookingRescheduleView's overlap check.
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
            return room, None, []

    # Every room is busy at some point in these dates. If this villa's manager
    # asked us to, see whether sliding the upcoming stays together opens one.
    if room_category.villa.auto_reassign_rooms and len(rooms) > 1:
        room, moves = plan_room_moves(room_category, check_in, check_out)
        if room is not None:
            logger.info(
                "Room type %s (villa %s) has space for %s to %s after moving %s booking(s)",
                room_category.pk, room_category.villa_id, check_in, check_out, len(moves),
            )
            return room, None, moves
        logger.info(
            "Room type %s (villa %s) is full for %s to %s even after reshuffling",
            room_category.pk, room_category.villa_id, check_in, check_out,
        )

    next_free_date = min((b.check_out for b in overlapping), default=None)
    return None, next_free_date, []


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


# How far ahead the public date picker greys out booked nights. A year is well
# past the 90-night maximum stay the enquiry form allows, and keeps the scan to
# one bounded query.
PUBLIC_AVAILABILITY_DAYS = 365


def fully_booked_nights(villa, days: int = PUBLIC_AVAILABILITY_DAYS) -> dict:
    """Which nights this villa has nothing left to sell, per room type.

    Returns {"any": [...], "<category id>": [...]} - each a sorted list of
    "YYYY-MM-DD" nights where every active room of that type is already taken.
    "any" is the intersection: nights where no room type of the villa has
    anything free, i.e. what to grey out before a visitor has picked a room.

    Read-only, and it only ever says *less* than the real check: a room type
    with no rooms defined yet is left out entirely rather than guessed at, so
    the picker never greys out a night it cannot honestly account for. The
    real answer is still find_available_room() at submit time.

    Nights, not days: a booking from the 3rd to the 5th takes the nights of
    the 3rd and the 4th - the 5th is a check-out morning and is free to be
    somebody else's arrival.
    """
    today = timezone.localdate()
    horizon = today + timedelta(days=days)

    rooms_by_category: dict = {}
    for room in Room.objects.filter(villa=villa, is_active=True).only("id", "category_id"):
        rooms_by_category.setdefault(room.category_id, set()).add(room.id)

    if not rooms_by_category:
        return {"any": []}

    all_room_ids = {rid for ids in rooms_by_category.values() for rid in ids}
    bookings = (
        Booking.objects.filter(
            villa=villa,
            room_id__in=all_room_ids,
            check_in__lt=horizon,
            check_out__gt=today,
        )
        .exclude(status=Booking.Status.CANCELLED)
        .only("room_id", "check_in", "check_out")
    )

    # {night: {room ids taken that night}}
    taken: dict = {}
    for booking in bookings:
        night = max(booking.check_in, today)
        end = min(booking.check_out, horizon)
        while night < end:
            taken.setdefault(night, set()).add(booking.room_id)
            night += timedelta(days=1)

    out: dict = {}
    per_category_nights = []
    for category_id, room_ids in rooms_by_category.items():
        nights = sorted(
            night for night, busy in taken.items() if room_ids.issubset(busy)
        )
        out[str(category_id)] = [n.isoformat() for n in nights]
        per_category_nights.append(set(nights))

    common = set.intersection(*per_category_nights) if per_category_nights else set()
    out["any"] = sorted(n.isoformat() for n in common)
    return out

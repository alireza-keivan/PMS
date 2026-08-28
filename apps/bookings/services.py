"""Calendar query and business logic, shared by the page view (apps.bookings.views)
and the JSON endpoint (apps.bookings.api) so both build the exact same data.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Max, Q, Sum
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from apps.bookings.models import Booking, BookingPayment
from apps.organizations.models import Membership
from apps.villas.models import Villa

CALENDAR_STATUS_LABELS = {
    "confirmed": _("Confirmed"),
    "checked_in": _("Checked in"),
    "checked_out": _("Checked out"),
    "blocked": _("Not available"),
    "payment_incomplete": _("Payment incomplete"),
}


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


def scoped_villas(request):
    """Active villas the logged-in user may see. Staff scoped to specific
    villas (Membership.villas) only see those; an empty M2M for staff means
    unrestricted, per that field's own help text. Owners/managers always see
    every active villa. Nothing in the codebase enforced Membership.villas
    before this - it's implemented fresh here.
    """
    org = request.organization
    membership = request.user.memberships.get(organization=org)
    villas = Villa.objects.filter(organization=org, is_active=True)
    if membership.role == Membership.Role.STAFF and membership.villas.exists():
        villas = villas.filter(id__in=membership.villas.values_list("id", flat=True))
    return list(villas.order_by("name")), membership


def build_calendar_data(request, start, days, q) -> dict:
    org = request.organization
    today = timezone.localdate()
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
        ).exclude(status=Booking.Status.CANCELLED).select_related("villa", "guest")
    )
    payments = payment_summary_by_booking(org, [b.id for b in bookings])

    groups = _build_groups(villas)
    items = [_build_item(b, today, payments.get(b.id, {}), membership.can_see_money) for b in bookings]
    return {"groups": groups, "items": items}


def _build_groups(villas: list) -> list:
    buckets = {}
    for v in villas:
        area_key = slugify(v.area) if v.area else "other"
        bucket = buckets.setdefault(area_key, {"label": v.area or str(_("Other")), "villa_ids": []})
        bucket["villa_ids"].append(str(v.id))

    ordered = sorted(buckets.items(), key=lambda kv: (kv[0] == "other", kv[1]["label"]))

    groups = []
    for area_key, bucket in ordered:
        group_id = f"area-{area_key}"
        # Collapse/expand is detected via vis-timeline's own click event
        # (properties.what === "group-label"), not a data-* attribute here -
        # vis-timeline runs custom group HTML through an XSS sanitizer that
        # doesn't allowlist data-* attributes, so one would just get stripped.
        toggle_html = f'<span class="cal-area-toggle">&#9662; {bucket["label"]}</span>'
        groups.append({"id": group_id, "content": toggle_html, "nestedGroups": bucket["villa_ids"]})
    for v in villas:
        groups.append({"id": str(v.id), "content": v.name})
    return groups


def _build_item(booking: Booking, today, payment: dict, can_see_money: bool) -> dict:
    status = calendar_status(booking, today, payment.get("amount_owed") or Decimal("0"))
    content = booking.guest.full_name if booking.has_guest_details else gettext("Booked")

    class_names = f"cal-status-{status}"
    if not booking.has_guest_details:
        class_names += " cal-no-detail"

    date_range = gettext("%(start)s – %(end)s") % {
        "start": booking.check_in.strftime("%d %b"),
        "end": booking.check_out.strftime("%d %b"),
    }
    nights_label = gettext("%(n)s nights") % {"n": booking.nights}
    title = "<br>".join([
        content,
        booking.villa.name,
        f"{date_range} ({nights_label})",
        booking.get_channel_display(),
    ])

    item = {
        "id": booking.id,
        "group": str(booking.villa_id),
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

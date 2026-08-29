"""Give every villa one bookable room per declared bedroom.

Rooms were introduced with a signal that created a single "Room 1" per villa,
regardless of how many bedrooms the villa said it had. So a villa advertising
"4 bedrooms" on the villa list still drew one row on the booking calendar -
the two screens read different sources of truth and disagreed.

This backfills the gap once for existing data; apps/villas/models.py's
sync_villa_rooms keeps them in step from here on.
"""

from django.db import migrations

ROOM_NAME_TEMPLATE = "Room {n}"


def add_missing_rooms(apps, schema_editor):
    Villa = apps.get_model("villas", "Villa")
    Room = apps.get_model("villas", "Room")

    new_rooms = []
    for villa in Villa.objects.all().iterator():
        existing = list(
            Room.objects.filter(villa=villa, is_active=True).values_list("name", flat=True)
        )
        target = max(villa.bedrooms or 1, len(existing))

        taken = set(existing)
        made = 0
        n = 1
        while len(existing) + made < target:
            name = ROOM_NAME_TEMPLATE.format(n=n)
            if name not in taken:
                new_rooms.append(
                    Room(
                        organization_id=villa.organization_id, villa=villa,
                        name=name, category="standard", is_active=True,
                    )
                )
                taken.add(name)
                made += 1
            n += 1

        # A villa whose rooms already outnumbered its bedrooms gets the number
        # corrected upward rather than losing rooms - see sync_villa_rooms.
        if villa.bedrooms != target:
            Villa.objects.filter(pk=villa.pk).update(bedrooms=target)

    Room.objects.bulk_create(new_rooms, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("villas", "0004_room"),
    ]

    operations = [
        # Not reversible on purpose: once created, these rooms are
        # indistinguishable from ones an operator added by hand and may already
        # carry bookings, so removing them again could destroy real data.
        migrations.RunPython(add_missing_rooms, migrations.RunPython.noop),
    ]

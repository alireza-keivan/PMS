"""Every villa gets at least one room, and every booking hangs off a room.

The calendar renders bookings on room rows only (villa rows are just headers),
so a villa with no rooms - or a booking with no room - would silently vanish
from the main screen. This backfill makes that impossible for existing data;
apps/villas/models.py's post_save signal keeps it true for new villas.
"""

from django.db import migrations

DEFAULT_ROOM_NAME = "Room 1"


def backfill_rooms(apps, schema_editor):
    Villa = apps.get_model("villas", "Villa")
    Room = apps.get_model("villas", "Room")
    Booking = apps.get_model("bookings", "Booking")

    for villa in Villa.objects.all():
        room = Room.objects.filter(villa=villa).order_by("id").first()
        if room is None:
            room = Room.objects.create(
                organization_id=villa.organization_id, villa=villa,
                name=DEFAULT_ROOM_NAME, category="standard", is_active=True,
            )
        # Only bookings that don't already point at a room - anything already
        # assigned (by the seed command, or by hand) is left alone.
        Booking.objects.filter(villa=villa, room__isnull=True).update(room=room)


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0004_booking_room"),
        ("villas", "0004_room"),
    ]

    operations = [
        migrations.RunPython(backfill_rooms, migrations.RunPython.noop),
    ]

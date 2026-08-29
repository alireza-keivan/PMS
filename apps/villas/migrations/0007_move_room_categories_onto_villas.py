"""Turn each room's fixed category string into one of its villa's own types.

Every villa gets the three types the product used to hard-code, so nothing
changes for anyone on day one - they just become editable per villa from here.
Rooms are then re-pointed at their own villa's matching type.
"""

from django.db import migrations

# The old Room.Category choices, in the order they were declared.
LEGACY_CATEGORIES = [("standard", "Standard"), ("deluxe", "Deluxe"), ("suite", "Suite")]


def move_categories_onto_villas(apps, schema_editor):
    Villa = apps.get_model("villas", "Villa")
    Room = apps.get_model("villas", "Room")
    RoomCategory = apps.get_model("villas", "RoomCategory")

    for villa in Villa.objects.all().iterator():
        by_value = {}
        for i, (value, label) in enumerate(LEGACY_CATEGORIES):
            by_value[value] = RoomCategory.objects.create(
                organization_id=villa.organization_id, villa=villa,
                name=label, sort_order=i,
            )
        for room in Room.objects.filter(villa=villa):
            category = by_value.get(room.category) or by_value["standard"]
            Room.objects.filter(pk=room.pk).update(new_category=category)


def drop_villa_categories(apps, schema_editor):
    """Reverse: room types go back to being a product-wide list, so the
    per-villa rows are no longer meaningful and the string column in 0008
    carries the value again."""
    apps.get_model("villas", "RoomCategory").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("villas", "0006_roomcategory"),
    ]

    operations = [
        migrations.RunPython(move_categories_onto_villas, drop_villa_categories),
    ]

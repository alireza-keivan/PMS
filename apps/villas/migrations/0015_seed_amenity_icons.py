"""Icon keys for the built-in amenities seeded in 0011.

The public villa page shows a small icon next to each amenity (feature
request: a mark like Airbnb's amenity list). The icon is picked by this key,
not by parsing the amenity's name - see templates/public/_amenity_icon.html
for the key -> SVG mapping. An amenity an operator types in themselves has
no key and falls back to a plain checkmark there.
"""

from django.db import migrations

# (English name from 0011, icon key)
ICONS = [
    ("Air conditioning", "ac"),
    ("Daily housekeeping", "housekeeping"),
    ("Electricity included", "electricity"),
    ("Free parking", "parking"),
    ("Full kitchen", "kitchen"),
    ("Pool", "pool"),
    ("Private garden", "garden"),
    ("Rice field view", "view"),
    ("WiFi", "wifi"),
]


def set_icons(apps, schema_editor):
    Amenity = apps.get_model("villas", "Amenity")
    for name_en, icon in ICONS:
        Amenity.objects.filter(name_en=name_en, organization=None).update(icon=icon)


def unset_icons(apps, schema_editor):
    Amenity = apps.get_model("villas", "Amenity")
    Amenity.objects.filter(
        name_en__in=[name_en for name_en, _ in ICONS], organization=None,
    ).update(icon="")


class Migration(migrations.Migration):
    dependencies = [
        ("villas", "0014_schedule_photo_sweep"),
    ]

    operations = [migrations.RunPython(set_icons, unset_icons)]

"""The amenities every operator starts with.

These are the ones a Bali villa is almost always described by, so nobody has
to type them in on their first villa. They have no organization, which is what
marks them as shared - anything an operator adds themselves carries their own
organization and is offered only back to them. See Amenity.available_to().

Both languages are filled in here because these are our words, not the
operator's. A custom one they type gets their wording in both fields instead.
"""

from django.db import migrations

# (English, Bahasa Indonesia)
BUILT_IN = [
    ("Air conditioning", "Pendingin ruangan"),
    ("Daily housekeeping", "Bersih-bersih harian"),
    ("Electricity included", "Listrik sudah termasuk"),
    ("Free parking", "Parkir gratis"),
    ("Full kitchen", "Dapur lengkap"),
    ("Pool", "Kolam renang"),
    ("Private garden", "Taman pribadi"),
    ("Rice field view", "Pemandangan sawah"),
    ("WiFi", "WiFi"),
]


def seed(apps, schema_editor):
    Amenity = apps.get_model("villas", "Amenity")
    for name_en, name_id in BUILT_IN:
        # Matched on the English name alone so an amenity seeded before this
        # migration existed is adopted rather than duplicated.
        amenity, created = Amenity.objects.get_or_create(
            name_en=name_en, organization=None, defaults={"name_id": name_id},
        )
        if not created and not amenity.name_id:
            amenity.name_id = name_id
            amenity.save(update_fields=["name_id"])


def unseed(apps, schema_editor):
    """Only removes the shared ones, and only the ones nothing is using -
    an operator's own list is never touched by rolling this back.
    """
    Amenity = apps.get_model("villas", "Amenity")
    Amenity.objects.filter(
        name_en__in=[name_en for name_en, _ in BUILT_IN],
        organization=None, room_categories__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("villas", "0010_remove_amenity_villas_remove_villa_base_monthly_rate_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]

"""Sample "things to do nearby" entries for Bamboo Loft Canggu (feature #8).

Gives the public villa page something real to show while the operator has
not yet uploaded their own activities and photos through the admin - see
ExperienceInline in apps.villas.admin. No photo is seeded here since there
are no real images to attach yet; the section already handles an activity
with no photo, and the operator can add one later from the admin.
"""

from django.db import migrations

# (name_en, name_id, description_en, description_id)
EXPERIENCES = [
    (
        "Canggu surf lesson",
        "Kelas surfing di Canggu",
        "A two-hour beginner surf lesson at Batu Bolong Beach, board and "
        "instructor included.",
        "Kelas surfing pemula dua jam di Pantai Batu Bolong, sudah termasuk "
        "papan dan instruktur.",
    ),
    (
        "Balinese cooking class",
        "Kelas memasak khas Bali",
        "Visit the local market, then cook a full Balinese meal with a "
        "family in their home kitchen.",
        "Kunjungi pasar lokal, lalu masak hidangan khas Bali bersama "
        "keluarga di dapur rumah mereka.",
    ),
    (
        "Tanah Lot sunset tour",
        "Tur matahari terbenam Tanah Lot",
        "An evening trip to the sea temple at Tanah Lot, timed for sunset.",
        "Perjalanan sore ke pura laut Tanah Lot, tepat saat matahari "
        "terbenam.",
    ),
]


def seed_experiences(apps, schema_editor):
    Villa = apps.get_model("villas", "Villa")
    Experience = apps.get_model("marketing", "Experience")

    villa = Villa.objects.filter(slug="bamboo-loft-canggu").first()
    if not villa:
        return

    for name_en, name_id, description_en, description_id in EXPERIENCES:
        experience, _created = Experience.objects.get_or_create(
            organization=villa.organization,
            name_en=name_en,
            defaults={
                "name_id": name_id,
                "description_en": description_en,
                "description_id": description_id,
            },
        )
        experience.villas.add(villa)


def unseed_experiences(apps, schema_editor):
    Villa = apps.get_model("villas", "Villa")
    Experience = apps.get_model("marketing", "Experience")

    villa = Villa.objects.filter(slug="bamboo-loft-canggu").first()
    if not villa:
        return

    Experience.objects.filter(
        organization=villa.organization,
        name_en__in=[name_en for name_en, *_ in EXPERIENCES],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("marketing", "0003_bookingenquiry"),
        ("villas", "0015_seed_amenity_icons"),
    ]

    operations = [migrations.RunPython(seed_experiences, unseed_experiences)]

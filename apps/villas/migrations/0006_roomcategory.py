"""Per-villa room types.

Room categories were a fixed, product-wide list (Standard/Deluxe/Suite) baked
into the Room model. Villas describe their rooms differently, so the list moves
onto the villa. This step only adds the new model and a temporary FK; the data
move and the old field's removal follow in 0007 and 0008.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0001_initial"),
        ("villas", "0005_backfill_rooms_to_bedrooms"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoomCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=80)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)ss",
                        to="organizations.organization",
                        verbose_name="operator",
                    ),
                ),
                (
                    "villa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="room_categories",
                        to="villas.villa",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "room categories",
                "ordering": ["sort_order", "name"],
                "unique_together": {("villa", "name")},
            },
        ),
        migrations.AddField(
            model_name="room",
            name="new_category",
            field=models.ForeignKey(
                blank=True, null=True,
                help_text="One of this villa's own room types.",
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="rooms",
                to="villas.roomcategory",
            ),
        ),
    ]

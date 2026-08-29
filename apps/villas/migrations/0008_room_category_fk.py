"""Retire the old fixed-choice column now that 0007 has moved the data."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("villas", "0007_move_room_categories_onto_villas"),
    ]

    operations = [
        migrations.RemoveField(model_name="room", name="category"),
        migrations.RenameField(model_name="room", old_name="new_category", new_name="category"),
    ]

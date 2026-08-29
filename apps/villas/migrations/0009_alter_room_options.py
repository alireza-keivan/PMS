"""Rooms list by type, then in the order they were created.

Sorting by name put "Deluxe 10" before "Deluxe 2", and reshuffled the
calendar's rows every time a room was renamed.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('villas', '0008_room_category_fk'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='room',
            options={'ordering': ['category__sort_order', 'id']},
        ),
    ]

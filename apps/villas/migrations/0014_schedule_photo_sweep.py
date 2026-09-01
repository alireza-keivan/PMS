"""Put the daily picture cleanup on the schedule.

Pictures picked on the villa form and never saved leave a row behind - see
PhotoQuerySet in models.py. apps/villas/tasks.py clears those up, and this is
what tells Celery beat to run it.

It lives in a migration rather than being set up by hand because this project
reads its schedule from the database (CELERY_BEAT_SCHEDULER = DatabaseScheduler),
so there is nothing in code that would otherwise say when this runs - and a
cleanup nobody remembers to switch on is a cleanup that never happens.

Nothing runs until a beat process is actually started; until then this is just
a row waiting patiently. Once it is running, the interval can be changed in
Django admin under Periodic Tasks without another deploy.
"""

from django.db import migrations

TASK = "apps.villas.tasks.prune_staged_photos"
NAME = "Clear up unsaved villa pictures"


def schedule(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    daily, _ = IntervalSchedule.objects.get_or_create(every=1, period="days")
    PeriodicTask.objects.get_or_create(
        task=TASK,
        defaults={
            "name": NAME,
            "interval": daily,
            # Nothing is urgent here - a leftover costs a few kilobytes - so if
            # the worker was down when this was due, it waits for the next day
            # instead of firing the moment it comes back.
            "one_off": False,
            "description": (
                "Deletes pictures that were uploaded on the villa form and never "
                "saved, and puts back ones that were taken off and never saved. "
                "Only touches edits left alone for more than a day."
            ),
        },
    )


def unschedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(task=TASK).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("villas", "0013_roomcategory_use_first_category_photos"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(schedule, unschedule),
    ]

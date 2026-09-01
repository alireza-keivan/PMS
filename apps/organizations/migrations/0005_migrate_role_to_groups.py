from django.db import migrations


def role_to_groups(apps, schema_editor):
    """Owner and Manager both become Manager; Staff stays Staff.

    Group membership is per-user, not per-Membership, so a user with
    memberships in more than one organization only needs handling once.
    """
    Membership = apps.get_model("organizations", "Membership")
    Group = apps.get_model("auth", "Group")
    manager_group = Group.objects.get(name="Manager")
    staff_group = Group.objects.get(name="Staff")
    for membership in Membership.objects.select_related("user").iterator():
        group = staff_group if membership.role == "staff" else manager_group
        membership.user.groups.add(group)


def groups_to_role(apps, schema_editor):
    """Best-effort reverse: Manager-group users become "manager", everyone
    else becomes "staff". The original Owner/Manager distinction can't be
    recovered from group membership alone - acceptable since this only runs
    as a fallback path, not the normal direction of travel.
    """
    Membership = apps.get_model("organizations", "Membership")
    Group = apps.get_model("auth", "Group")
    manager_group = Group.objects.get(name="Manager")
    manager_user_ids = set(manager_group.user_set.values_list("id", flat=True))
    for membership in Membership.objects.iterator():
        membership.role = "manager" if membership.user_id in manager_user_ids else "staff"
        membership.save(update_fields=["role"])


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0004_create_permission_groups"),
    ]

    operations = [
        migrations.RunPython(role_to_groups, groups_to_role),
    ]

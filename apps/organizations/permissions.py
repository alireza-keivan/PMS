"""Manager vs. Staff, in one place.

Two Django Groups ("Manager", "Staff") are the entire permission model - no
custom Permission codenames, since every check this app makes is really just
"is this a Manager". Superusers count as Manager everywhere so an admin
account isn't locked out of manager-only pages without also joining a group.
"""

MANAGER_GROUP = "Manager"
STAFF_GROUP = "Staff"


def is_manager(user) -> bool:
    return user.is_superuser or user.groups.filter(name=MANAGER_GROUP).exists()


def can_see_money(user) -> bool:
    return is_manager(user)

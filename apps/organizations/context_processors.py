from apps.organizations.permissions import is_manager


def organization(request):
    """Expose the active tenant and its sync tier to every template.

    Templates use `organization.has_live_sync` to decide whether a screen may
    describe data as up to date.
    """
    return {"organization": getattr(request, "organization", None)}


def user_role(request):
    """Expose Manager-vs-Staff to every template, mainly for the nav - a
    Staff user should never see a link to a page they'll just get a 403 on.
    Individual views still pass their own `is_manager` for page content
    (buttons, forms), since that's specific to what's on that one page.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"is_manager": False}
    return {"is_manager": is_manager(user)}

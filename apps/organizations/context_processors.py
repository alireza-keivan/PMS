def organization(request):
    """Expose the active tenant and its sync tier to every template.

    Templates use `organization.has_live_sync` to decide whether a screen may
    describe data as up to date.
    """
    return {"organization": getattr(request, "organization", None)}

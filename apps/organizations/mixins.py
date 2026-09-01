from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from apps.organizations.permissions import is_manager


class ManagerRequiredMixin(LoginRequiredMixin):
    """Gate a view to Manager-group users (and superusers).

    Login is checked first (redirect to the login page); a logged-in Staff
    user gets a hard 403 instead - the page exists, they're just not allowed
    to use it.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not is_manager(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

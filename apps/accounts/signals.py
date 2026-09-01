"""Who signed in, who failed, who signed out - written to the log.

There is no other record of this anywhere: sessions leave no trail and the
admin only shows last_login. When a client asks "did anyone open my dashboard
last night", these lines are the answer.
"""

import logging

from allauth.account.signals import user_signed_up
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _method(request) -> str:
    """Google or password - taken from where the sign-in came from."""
    if request is not None and request.path_info.startswith("/auth/"):
        return "google"
    return "password"


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    logger.info("User %s (%s) signed in with %s", user.pk, user.email, _method(request))


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    if user is not None:
        logger.info("User %s (%s) signed out", user.pk, user.email)


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request=None, **kwargs):
    # Never log the password, and never confirm whether the address exists -
    # the log file is not the place to leak either.
    logger.warning(
        "Failed sign-in attempt for %s", credentials.get("username") or "unknown"
    )


@receiver(user_signed_up)
def log_signup(sender, request, user, **kwargs):
    logger.info(
        "User %s (%s) signed up and now needs a business", user.pk, user.email
    )

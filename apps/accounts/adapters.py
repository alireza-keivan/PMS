"""How allauth is allowed to create and fill in accounts.

Two small overrides, both about keeping the front door narrow:

  - nobody signs themselves up with a password (accounts come from Google, or
    from an admin);
  - a Google account arrives with a name we can use, so use it.

Deliberately not done here: creating the person's Organization. A brand new
user has no business yet, and guessing one from their Google profile would put
a name in front of them they never chose. The welcome form asks instead - see
apps/accounts/views.py.
"""

import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """No password self-signup. Google or an admin only."""
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        """Anyone with a Google account can start. They land on the welcome
        form, which is where their business gets created."""
        return True

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        # allauth splits Google's "name" into first/last for the stock user
        # model; ours keeps one field, so put it back together.
        full_name = (data.get("name") or "").strip()
        if not full_name:
            full_name = " ".join(
                part for part in (data.get("first_name"), data.get("last_name")) if part
            ).strip()
        if full_name:
            user.full_name = full_name
        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        logger.info(
            "New account %s created from %s sign-in (%s)",
            user.pk,
            sociallogin.account.provider,
            user.email,
        )
        return user

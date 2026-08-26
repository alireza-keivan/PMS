"""Authentication for staff and owners.

Guests are deliberately absent from this app. They never hold an account - see
apps/guests/ for how they reach the portal.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Email-based manager - there are no usernames in this product."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Staff, managers and villa owners. Not guests.

    A user belongs to one or more organizations through Membership, which is
    where their role is defined - the flags here only govern Django admin access.
    """

    username = None
    email = models.EmailField(_("email address"), unique=True)
    full_name = models.CharField(_("full name"), max_length=150, blank=True)
    phone = models.CharField(
        _("WhatsApp number"),
        max_length=32,
        blank=True,
        help_text=_("Full international format, e.g. +6281234567890."),
    )
    preferred_language = models.CharField(
        _("language"), max_length=5, choices=[("en", "English"), ("id", "Bahasa Indonesia")],
        default="en",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.full_name or self.email

import pytest
from django.db import IntegrityError

from apps.accounts.models import User


def test_user_logs_in_with_email_not_username(db):
    user = User.objects.create_user(email="owner@example.com", password="testpass123")
    assert user.USERNAME_FIELD == "email"
    assert not hasattr(user, "username") or user.username is None
    assert user.check_password("testpass123")


def test_create_superuser_sets_both_flags(db):
    admin = User.objects.create_superuser(email="admin@example.com", password="testpass123")
    assert admin.is_staff is True
    assert admin.is_superuser is True


def test_email_must_be_unique(db):
    User.objects.create_user(email="dup@example.com", password="testpass123")
    with pytest.raises(IntegrityError):
        User.objects.create_user(email="dup@example.com", password="testpass123")


def test_email_is_required():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="testpass123")

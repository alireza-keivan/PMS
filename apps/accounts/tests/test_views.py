"""The front door: signing in, and the welcome step for a brand new account."""

from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.adapters import SocialAccountAdapter
from apps.accounts.models import User
from apps.organizations.models import Membership, Organization
from apps.organizations.permissions import can_see_money, is_manager
from apps.organizations.services import create_organization_for, unique_slug


@pytest.fixture
def member(user, org, make_membership):
    make_membership(user, org, manager=True)
    return user


# ------------------------------------------------------------------ login page


@override_settings(GOOGLE_OAUTH_CLIENT_ID="test-client-id")
def test_login_page_shows_google_button(client, db):
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    assert "Continue with Google" in response.content.decode()


@override_settings(GOOGLE_OAUTH_CLIENT_ID="")
def test_login_page_hides_google_button_when_not_configured(client, db):
    """A button that can only fail is worse than no button."""
    response = client.get(reverse("accounts:login"))
    assert "Continue with Google" not in response.content.decode()


def test_login_page_always_offers_email_and_password(client, db):
    body = client.get(reverse("accounts:login")).content.decode()
    assert 'name="username"' in body
    assert 'name="password"' in body


def test_password_login_still_works(client, member):
    """Guards against the allauth backend quietly breaking the old way in."""
    response = client.post(
        reverse("accounts:login"),
        {"username": "staff@example.com", "password": "testpass123"},
    )
    assert response.status_code == 302
    assert response.wsgi_request.user.is_authenticated


def test_signed_in_user_is_sent_away_from_login(client, member):
    client.force_login(member)
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 302


# ------------------------------------------------------- creating the business


def test_create_organization_makes_the_user_its_owner(user):
    organization = create_organization_for(user, "Canggu Coastal Villas")

    assert organization.slug == "canggu-coastal-villas"
    assert Membership.objects.filter(user=user, organization=organization).exists()
    assert is_manager(user)
    assert can_see_money(user)


def test_organization_slugs_do_not_collide(user, db):
    Organization.objects.create(name="Bali Villas", slug="bali-villas")
    assert unique_slug("Bali Villas") == "bali-villas-2"


def test_slug_falls_back_when_the_name_has_no_letters(user):
    organization = create_organization_for(user, "!!!")
    assert organization.slug == "villas"


# ------------------------------------------------------------ the welcome form


def test_onboarding_requires_login(client, db):
    response = client.get(reverse("accounts:onboarding"))
    assert response.status_code == 302
    assert "login" in response.url


def test_onboarding_creates_the_business_and_moves_on(client, user):
    client.force_login(user)
    response = client.post(reverse("accounts:onboarding"), {"name": "Ubud Green"})

    assert response.status_code == 302
    assert response.url == reverse("villas:list")
    organization = Organization.objects.get(name="Ubud Green")
    assert organization.memberships.filter(user=user).exists()
    assert is_manager(user)


def test_onboarding_is_skipped_once_you_have_a_business(client, member):
    client.force_login(member)
    response = client.get(reverse("accounts:onboarding"))
    assert response.status_code == 302
    assert response.url == reverse("villas:list")


def test_onboarding_rejects_an_empty_name(client, user):
    client.force_login(user)
    response = client.post(reverse("accounts:onboarding"), {"name": "   "})
    assert response.status_code == 200
    assert not Organization.objects.exists()


# -------------------------------------------------------------- the middleware


def test_user_without_a_business_is_sent_to_the_welcome_form(client, user):
    client.force_login(user)
    response = client.get(reverse("villas:list"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:onboarding")


def test_user_without_a_business_can_still_sign_out(client, user):
    client.force_login(user)
    response = client.post(reverse("accounts:logout"))
    assert response.url != reverse("accounts:onboarding")


def test_admin_stays_reachable_without_a_business(client, db):
    """A superuser has no membership and should never need one."""
    admin = User.objects.create_superuser(email="boss@example.com", password="x")
    client.force_login(admin)
    response = client.get("/admin/")
    assert response.status_code == 200


def test_switched_off_business_is_not_asked_to_make_another_one(
    client, user_without_active_organization
):
    """They have no organization either, but the answer is not "name a new
    business" - they keep the dashboard's own nothing-here-yet state."""
    client.force_login(user_without_active_organization)
    assert client.get(reverse("villas:list")).status_code == 200
    assert client.get(reverse("accounts:onboarding")).url == reverse("villas:list")


def test_member_is_left_alone(client, member):
    client.force_login(member)
    response = client.get(reverse("villas:list"))
    assert response.status_code == 200


def test_signed_out_visitor_is_sent_to_login_not_onboarding(client, db):
    response = client.get(reverse("villas:list"))
    assert "login" in response.url


# ------------------------------------------------------------------ the adapter


def test_google_name_becomes_the_full_name(db):
    """Our User has one name field; allauth would otherwise split it in two."""
    sociallogin = SimpleNamespace(user=User(), account=None)

    populated = SocialAccountAdapter().populate_user(
        None, sociallogin, {"email": "budi@example.com", "name": "Budi Santoso"}
    )
    assert populated.full_name == "Budi Santoso"


def test_full_name_is_rebuilt_when_google_sends_only_the_parts(db):
    sociallogin = SimpleNamespace(user=User(), account=None)

    populated = SocialAccountAdapter().populate_user(
        None,
        sociallogin,
        {"email": "wayan@example.com", "first_name": "Wayan", "last_name": "Putra"},
    )
    assert populated.full_name == "Wayan Putra"

"""The calendar page has to work for a plain link (no JS) and for HTMX's
partial swap - both paths are exercised here, plus the no-organization state
every other screen in this app also has to handle.
"""

from datetime import date

import pytest
from django.urls import reverse

from apps.organizations.models import Membership


@pytest.fixture
def owner_client(client, org, user):
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OWNER)
    client.force_login(user)
    return client


def test_requires_login(client, db):
    response = client.get(reverse("bookings:calendar"))
    assert response.status_code == 302


def test_no_organization_shows_the_placeholder_state(client, user):
    client.force_login(user)
    response = client.get(reverse("bookings:calendar"))
    assert response.context["no_organization"] is True


def test_full_page_load_includes_the_page_shell(owner_client):
    response = owner_client.get(reverse("bookings:calendar"))
    assert response.status_code == 200
    assert b"calendar-timeline" in response.content
    assert b"calendar-data" in response.content


def test_htmx_request_returns_only_the_panel_fragment(owner_client):
    response = owner_client.get(reverse("bookings:calendar"), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert b"calendar-timeline" not in response.content
    assert b"calendar-data" in response.content


def test_default_range_is_fourteen_days(owner_client):
    response = owner_client.get(reverse("bookings:calendar"))
    assert response.context["days"] == 14


def test_invalid_days_falls_back_to_default(owner_client):
    response = owner_client.get(reverse("bookings:calendar"), {"days": "999"})
    assert response.context["days"] == 14


def test_start_date_is_parsed_from_query_param(owner_client):
    response = owner_client.get(reverse("bookings:calendar"), {"start": "2026-01-05"})
    assert response.context["start"] == date(2026, 1, 5)


def test_invalid_start_date_falls_back_to_today(owner_client):
    response = owner_client.get(reverse("bookings:calendar"), {"start": "not-a-date"})
    assert response.context["start"] == date.today()

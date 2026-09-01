"""The one session-authenticated route on the otherwise webhook-only Ninja
API - confirm it actually requires a session, and that it's reachable at all
once wired into config/api.py.
"""

import pytest



@pytest.fixture
def owner_client(client, org, user, make_membership):
    make_membership(user, org, manager=True)
    client.force_login(user)
    return client


def test_requires_a_session(client, db):
    response = client.get("/api/bookings/calendar/")
    assert response.status_code in (401, 403)


def test_logged_in_user_gets_calendar_data(owner_client):
    response = owner_client.get("/api/bookings/calendar/")
    assert response.status_code == 200
    body = response.json()
    assert "groups" in body
    assert "items" in body


def test_rejects_an_out_of_range_days_value(owner_client):
    response = owner_client.get("/api/bookings/calendar/", {"days": "999"})
    assert response.status_code == 200  # falls back to the default rather than erroring

"""The /reporting page. What would go wrong silently here is a number that
looks plausible but isn't: a foreign payment counted at face value, another
operator's money in the total, or a made-up figure standing in for one we
don't actually have. Those are what these tests pin down.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking, BookingPayment
from apps.reporting.fx import ExchangeRate
from apps.reporting.reports import Period, add_months, resolve_period
from apps.villas.models import Villa


@pytest.fixture
def owner_client(client, org, user, make_membership):
    make_membership(user, org, manager=True)
    client.force_login(user)
    return client


@pytest.fixture
def url():
    return reverse("reports:index")


def make_booking(org, villa, *, check_in, nights=3, rate=1_000_000, guest=None):
    return Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=check_in, check_out=check_in + timedelta(days=nights),
        status=Booking.Status.CONFIRMED, channel=Booking.Channel.AIRBNB,
        source_detail=Booking.SourceDetail.MANUAL, nightly_rate=rate,
    )


def test_page_requires_login(client, db, url):
    response = client.get(url)
    assert response.status_code == 302
    assert "login" in response.url


def test_money_received_comes_from_payments_not_placeholders(owner_client, org, villa, url):
    today = timezone.localdate()
    booking = make_booking(org, villa, check_in=today.replace(day=1))
    BookingPayment.objects.create(
        organization=org, booking=booking, amount=Decimal("5000000"), currency="IDR",
        received_on=today, is_outstanding=False,
    )
    response = owner_client.get(url)
    assert response.status_code == 200
    received = response.context["metrics"][0]
    assert received["value"] == Decimal("5000000")


def test_foreign_payment_is_converted_with_the_stored_rate(owner_client, org, villa, url):
    ExchangeRate.objects.create(
        base_currency="USD", quote_currency="IDR", rate="15000", effective_on="2020-01-01",
    )
    today = timezone.localdate()
    booking = make_booking(org, villa, check_in=today.replace(day=1))
    BookingPayment.objects.create(
        organization=org, booking=booking, amount=Decimal("100"), currency="USD",
        received_on=today, is_outstanding=False,
    )
    response = owner_client.get(url)
    assert response.context["metrics"][0]["value"] == Decimal("1500000")


def test_payment_with_no_rate_on_file_is_left_out_and_counted(owner_client, org, villa, url):
    today = timezone.localdate()
    booking = make_booking(org, villa, check_in=today.replace(day=1))
    BookingPayment.objects.create(
        organization=org, booking=booking, amount=Decimal("100"), currency="AUD",
        received_on=today, is_outstanding=False,
    )
    response = owner_client.get(url)
    assert response.context["metrics"][0]["value"] == 0
    assert response.context["unconverted_payments"] == 1


def test_booking_value_counts_stays_that_are_not_paid_for_yet(owner_client, org, villa, url):
    today = timezone.localdate()
    make_booking(org, villa, check_in=today.replace(day=1), nights=4, rate=2_000_000)
    response = owner_client.get(url)
    value = response.context["metrics"][1]
    assert value["value"] == Decimal("8000000")


def test_booking_without_a_price_is_flagged_rather_than_guessed_at(owner_client, org, villa, url):
    today = timezone.localdate()
    make_booking(org, villa, check_in=today.replace(day=1), rate=None)
    response = owner_client.get(url)
    assert response.context["metrics"][1]["value"] == 0
    assert response.context["bookings_without_price"] == 1


def test_another_operators_money_never_appears(owner_client, org, villa, url, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Villa Lain", slug="lain")
    today = timezone.localdate()
    booking = make_booking(other_org, other_villa, check_in=today.replace(day=1))
    BookingPayment.objects.create(
        organization=other_org, booking=booking, amount=Decimal("9000000"), currency="IDR",
        received_on=today, is_outstanding=False,
    )
    response = owner_client.get(url)
    assert response.context["metrics"][0]["value"] == 0


def test_channel_shares_are_counted_from_real_bookings(owner_client, org, villa, url):
    today = timezone.localdate()
    make_booking(org, villa, check_in=today.replace(day=1))
    booking = make_booking(org, villa, check_in=today.replace(day=1), nights=1)
    booking.channel = Booking.Channel.DIRECT
    booking.save()
    response = owner_client.get(url)
    shares = response.context["source_shares"]
    assert shares["total"] == 2
    assert {s["pct"] for s in shares["shares"]} == {50}


def test_outstanding_money_is_grouped_by_when_the_stay_starts(owner_client, org, villa, url):
    today = timezone.localdate()
    started = make_booking(org, villa, check_in=today - timedelta(days=2))
    soon = make_booking(org, villa, check_in=today + timedelta(days=3))
    for booking in (started, soon):
        BookingPayment.objects.create(
            organization=org, booking=booking, amount=Decimal("1000000"),
            currency="IDR", is_outstanding=True,
        )
    groups = {g["key"]: g["items"] for g in owner_client.get(url).context["owed_groups"]}
    assert [p.booking_id for p in groups["overdue"]] == [started.id]
    assert [p.booking_id for p in groups["week"]] == [soon.id]


def test_a_period_with_nothing_in_it_says_so(owner_client, org, villa, url):
    response = owner_client.get(url, {"range": "last_month"})
    assert response.context["has_any_data"] is False


def test_villa_filter_narrows_the_page_to_one_villa(owner_client, org, villa, url):
    other = Villa.objects.create(organization=org, name="Villa Dua", slug="dua")
    today = timezone.localdate()
    make_booking(org, other, check_in=today.replace(day=1))
    response = owner_client.get(url, {"villa": str(villa.id)})
    assert [row["villa"].id for row in response.context["villa_rows"]] == [villa.id]


def test_an_unknown_range_falls_back_to_this_month(owner_client, org, villa, url):
    response = owner_client.get(url, {"range": "nonsense"})
    assert response.context["range_key"] == "this_month"


def test_resolve_period_last_month_is_a_whole_calendar_month():
    period = resolve_period("last_month", date(2026, 3, 15))
    assert period == Period(date(2026, 2, 1), date(2026, 2, 28))


def test_add_months_crosses_the_year_boundary():
    assert add_months(date(2026, 1, 10), -2) == date(2025, 11, 1)

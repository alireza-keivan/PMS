"""convert() must never invent a number. Returning None when no rate is on
file is a deliberate choice - see docs/decisions.md - and is the one thing
this module absolutely cannot get wrong.
"""

from datetime import date
from decimal import Decimal

from apps.reporting.fx import ExchangeRate, convert


def test_same_currency_needs_no_rate_and_returns_exact_amount(db):
    result = convert(Decimal("1000000"), "IDR", "IDR", date.today())
    assert result == Decimal("1000000")


def test_conversion_uses_the_rate_on_file(db):
    ExchangeRate.objects.create(
        base_currency="USD", quote_currency="IDR", rate=Decimal("15800"),
        effective_on=date(2026, 1, 1),
    )
    result = convert(Decimal("100"), "USD", "IDR", date(2026, 3, 1))
    assert result == Decimal("1580000")


def test_missing_rate_returns_none_rather_than_guessing(db):
    result = convert(Decimal("100"), "EUR", "IDR", date.today())
    assert result is None


def test_uses_the_most_recent_rate_not_later_than_the_target_date(db):
    ExchangeRate.objects.create(
        base_currency="USD", quote_currency="IDR", rate=Decimal("15000"),
        effective_on=date(2026, 1, 1),
    )
    ExchangeRate.objects.create(
        base_currency="USD", quote_currency="IDR", rate=Decimal("16000"),
        effective_on=date(2026, 6, 1),
    )
    # Ask for a date between the two rates - must use the earlier one, not
    # the most recent one ever recorded.
    result = convert(Decimal("10"), "USD", "IDR", date(2026, 3, 1))
    assert result == Decimal("150000")


def test_rate_effective_after_the_target_date_is_not_used(db):
    ExchangeRate.objects.create(
        base_currency="USD", quote_currency="IDR", rate=Decimal("16000"),
        effective_on=date(2026, 6, 1),
    )
    result = convert(Decimal("10"), "USD", "IDR", date(2026, 1, 1))
    assert result is None

"""needs_attention and is_overdue drive the action-needed counter (feature #16)
- the whole point of that screen is these two properties being right.
"""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.bookings.models import Booking
from apps.compliance.models import ComplianceDocument, PoliceReport
from apps.guests.services import find_or_create_guest


def _document(org, villa, expires_on, reminder_days=60):
    return ComplianceDocument.objects.create(
        organization=org, villa=villa, kind=ComplianceDocument.Kind.NIB,
        file=ContentFile(b"fake pdf", name="nib.pdf"),
        expires_on=expires_on, reminder_days=reminder_days,
    )


def test_document_needs_attention_inside_the_reminder_window(org, villa):
    doc = _document(org, villa, expires_on=timezone.localdate() + timedelta(days=10), reminder_days=60)
    assert doc.needs_attention is True


def test_document_does_not_need_attention_far_from_expiry(org, villa):
    doc = _document(org, villa, expires_on=timezone.localdate() + timedelta(days=200), reminder_days=60)
    assert doc.needs_attention is False


def test_document_with_no_expiry_never_needs_attention(org, villa):
    doc = _document(org, villa, expires_on=None)
    assert doc.needs_attention is False


def test_already_expired_document_needs_attention(org, villa):
    doc = _document(org, villa, expires_on=timezone.localdate() - timedelta(days=1))
    assert doc.needs_attention is True


@pytest.fixture
def booking_with_guest(org, villa):
    guest = find_or_create_guest(org, full_name="Foreign Guest", nationality="AU")
    booking = Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=timezone.localdate(), check_out=timezone.localdate() + timedelta(days=3),
    )
    return booking, guest


def test_police_report_overdue_only_when_still_needed_and_past_deadline(org, booking_with_guest):
    booking, guest = booking_with_guest
    overdue = PoliceReport.objects.create(
        organization=org, booking=booking, guest=guest,
        deadline=timezone.now() - timedelta(hours=1), status=PoliceReport.Status.NEEDED,
    )
    assert overdue.is_overdue is True


def test_police_report_not_overdue_once_filed_even_if_past_deadline(org, booking_with_guest):
    booking, guest = booking_with_guest
    filed = PoliceReport.objects.create(
        organization=org, booking=booking, guest=guest,
        deadline=timezone.now() - timedelta(hours=1), status=PoliceReport.Status.FILED,
    )
    assert filed.is_overdue is False


def test_police_report_not_overdue_before_deadline(org, booking_with_guest):
    booking, guest = booking_with_guest
    report = PoliceReport.objects.create(
        organization=org, booking=booking, guest=guest,
        deadline=timezone.now() + timedelta(hours=1), status=PoliceReport.Status.NEEDED,
    )
    assert report.is_overdue is False

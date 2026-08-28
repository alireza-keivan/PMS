"""The action-needed view is a status board, not a checklist to trust
blindly - the tests worth having are that it only ever surfaces this
organization's (and this staff member's assigned villas') items, that
marking a police report done actually removes it from the list, and that
adding a document can't attach it to someone else's villa.
"""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking
from apps.compliance.models import ComplianceDocument, PoliceReport
from apps.guests.services import find_or_create_guest
from apps.organizations.models import Membership
from apps.villas.models import Villa


@pytest.fixture
def owner_client(client, org, user):
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OWNER)
    client.force_login(user)
    return client


def _document(org, villa, expires_on=None, reminder_days=60):
    return ComplianceDocument.objects.create(
        organization=org, villa=villa, kind=ComplianceDocument.Kind.NIB,
        file=SimpleUploadedFile("doc.pdf", b"fake pdf"),
        expires_on=expires_on, reminder_days=reminder_days,
    )


def _police_report(org, villa, deadline, status=PoliceReport.Status.NEEDED):
    guest = find_or_create_guest(org, full_name="Foreign Guest", nationality="AU")
    booking = Booking.objects.create(
        organization=org, villa=villa, guest=guest,
        check_in=timezone.localdate(), check_out=timezone.localdate() + timedelta(days=3),
    )
    return PoliceReport.objects.create(
        organization=org, booking=booking, guest=guest, deadline=deadline, status=status,
    )


def test_no_organization_shows_the_placeholder_state(client, user):
    client.force_login(user)
    response = client.get(reverse("compliance:action_needed"))
    assert response.context["no_organization"] is True


def test_action_needed_only_shows_this_organizations_items(owner_client, org, other_org, villa):
    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    mine = _document(org, villa, expires_on=timezone.localdate())
    _document(other_org, other_villa, expires_on=timezone.localdate())

    response = owner_client.get(reverse("compliance:action_needed"))
    assert response.context["documents_needing_attention"] == [mine]


def test_action_needed_excludes_documents_far_from_expiry(owner_client, org, villa):
    _document(org, villa, expires_on=timezone.localdate() + timedelta(days=200), reminder_days=60)

    response = owner_client.get(reverse("compliance:action_needed"))
    assert response.context["documents_needing_attention"] == []


def test_action_needed_includes_business_wide_documents_with_no_villa(owner_client, org):
    doc = _document(org, villa=None, expires_on=timezone.localdate())
    response = owner_client.get(reverse("compliance:action_needed"))
    assert doc in response.context["documents_needing_attention"]


def test_action_needed_excludes_police_reports_too_far_in_the_future(owner_client, org, villa):
    _police_report(org, villa, deadline=timezone.now() + timedelta(days=30))
    response = owner_client.get(reverse("compliance:action_needed"))
    assert list(response.context["police_reports"]) == []


def test_action_needed_includes_overdue_police_reports(owner_client, org, villa):
    report = _police_report(org, villa, deadline=timezone.now() - timedelta(hours=1))
    response = owner_client.get(reverse("compliance:action_needed"))
    assert list(response.context["police_reports"]) == [report]


def test_action_needed_excludes_already_filed_police_reports(owner_client, org, villa):
    _police_report(org, villa, deadline=timezone.now() - timedelta(hours=1), status=PoliceReport.Status.FILED)
    response = owner_client.get(reverse("compliance:action_needed"))
    assert list(response.context["police_reports"]) == []


def test_staff_scoped_to_specific_villas_only_sees_those_items(org, user, villa):
    other_villa = Villa.objects.create(organization=org, name="Not Assigned", slug="not-assigned")
    membership = Membership.objects.create(user=user, organization=org, role=Membership.Role.STAFF)
    membership.villas.add(villa)
    _document(org, other_villa, expires_on=timezone.localdate())

    from django.test import Client

    client = Client()
    client.force_login(user)
    response = client.get(reverse("compliance:action_needed"))
    assert response.context["documents_needing_attention"] == []


def test_document_list_shows_every_document_regardless_of_urgency(owner_client, org, villa):
    doc = _document(org, villa, expires_on=timezone.localdate() + timedelta(days=300))
    response = owner_client.get(reverse("compliance:documents"))
    assert doc in response.context["documents"]


def test_add_document_creates_it_for_the_current_organization(owner_client, org, villa):
    response = owner_client.post(reverse("compliance:add_document"), {
        "kind": ComplianceDocument.Kind.SLF,
        "villa": villa.pk,
        "file": SimpleUploadedFile("slf.pdf", b"fake pdf"),
        "reminder_days": 30,
    })
    assert response.status_code == 302
    doc = ComplianceDocument.objects.get(organization=org, kind=ComplianceDocument.Kind.SLF)
    assert doc.villa == villa


def test_add_document_cannot_attach_to_another_organizations_villa(owner_client, org, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    response = owner_client.post(reverse("compliance:add_document"), {
        "kind": ComplianceDocument.Kind.SLF,
        "villa": other_villa.pk,
        "file": SimpleUploadedFile("slf.pdf", b"fake pdf"),
        "reminder_days": 30,
    })
    assert response.status_code == 200  # form re-rendered with a validation error
    assert not ComplianceDocument.objects.filter(organization=org).exists()


def test_mark_police_report_done_updates_status_and_who(owner_client, org, villa, user):
    report = _police_report(org, villa, deadline=timezone.now() - timedelta(hours=1))
    owner_client.post(reverse("compliance:mark_police_report_done", args=[report.pk]))
    report.refresh_from_db()
    assert report.status == PoliceReport.Status.FILED
    assert report.marked_done_by == user
    assert report.marked_done_at is not None


def test_mark_police_report_done_removes_it_from_the_htmx_response(owner_client, org, villa):
    report = _police_report(org, villa, deadline=timezone.now() - timedelta(hours=1))
    response = owner_client.post(
        reverse("compliance:mark_police_report_done", args=[report.pk]), HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert b"action-needed-count" in response.content
    assert str(report.guest.full_name).encode() not in response.content


def test_cannot_mark_another_organizations_police_report_done(owner_client, other_org):
    other_villa = Villa.objects.create(organization=other_org, name="Other", slug="other")
    report = _police_report(other_org, other_villa, deadline=timezone.now() - timedelta(hours=1))
    response = owner_client.post(reverse("compliance:mark_police_report_done", args=[report.pk]))
    assert response.status_code == 404
    report.refresh_from_db()
    assert report.status == PoliceReport.Status.NEEDED

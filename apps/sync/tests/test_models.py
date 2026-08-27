from apps.sync.models import RawPayload, SyncAccount, SyncRun


def test_beds24_account_is_not_tied_to_one_villa(org):
    """One Beds24 login covers every villa in the organization."""
    account = SyncAccount.objects.create(
        organization=org, provider=SyncAccount.Provider.BEDS24,
        beds24_property_id="12345", refresh_token="secret-token",
    )
    assert account.villa is None


def test_ical_account_is_tied_to_one_villa(org, villa):
    account = SyncAccount.objects.create(
        organization=org, provider=SyncAccount.Provider.ICAL, villa=villa,
        ical_url="https://airbnb.com/calendar/ical/123.ics", ical_channel="airbnb",
    )
    assert account.villa == villa


def test_sync_run_records_the_outcome(org, villa):
    account = SyncAccount.objects.create(
        organization=org, provider=SyncAccount.Provider.ICAL, villa=villa,
        ical_url="https://example.com/cal.ics",
    )
    run = SyncRun.objects.create(
        organization=org, account=account, trigger=SyncRun.Trigger.SCHEDULED,
        result=SyncRun.Result.OK, bookings_created=2, bookings_updated=1,
    )
    assert run.account == account
    assert run in account.runs.all()


def test_raw_payload_keeps_the_original_body_untouched(org, villa):
    account = SyncAccount.objects.create(
        organization=org, provider=SyncAccount.Provider.ICAL, villa=villa,
        ical_url="https://example.com/cal.ics",
    )
    body = {"bookId": "abc123", "guestName": "Jane Doe", "roomId": 9}
    payload = RawPayload.objects.create(organization=org, account=account, body=body)
    payload.refresh_from_db()
    assert payload.body == body

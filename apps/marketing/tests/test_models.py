from apps.marketing.models import Experience, RateSnapshot


def test_rate_snapshot_keeps_amount_and_channel_together(org, villa):
    snapshot = RateSnapshot.objects.create(
        organization=org, villa=villa, channel="airbnb",
        stay_date="2026-12-24", amount="2500000", currency="IDR",
    )
    assert snapshot.channel == "airbnb"
    assert snapshot.currency == "IDR"


def test_experience_can_be_offered_at_multiple_villas(org, villa):
    from apps.villas.models import Villa

    second_villa = Villa.objects.create(organization=org, name="Villa Kedua", slug="kedua")
    tour = Experience.objects.create(organization=org, name_en="Monkey Forest Tour")
    tour.villas.add(villa, second_villa)

    assert set(tour.villas.all()) == {villa, second_villa}

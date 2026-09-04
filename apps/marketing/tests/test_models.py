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


def test_an_over_long_activity_description_is_refused_with_a_plain_message():
    from apps.marketing.forms import ExperienceForm
    from apps.marketing.models import EXPERIENCE_DESCRIPTION_MAX_LENGTH

    too_long = "a" * (EXPERIENCE_DESCRIPTION_MAX_LENGTH + 1)
    form = ExperienceForm(data={
        "name_en": "Sunrise trek", "description_en": too_long, "commission_percent": "10",
    })

    assert not form.is_valid()
    assert "description_en" in form.errors
    assert str(EXPERIENCE_DESCRIPTION_MAX_LENGTH) in form.errors["description_en"][0]


def test_a_description_right_on_the_limit_is_accepted():
    from apps.marketing.forms import ExperienceForm
    from apps.marketing.models import EXPERIENCE_DESCRIPTION_MAX_LENGTH

    form = ExperienceForm(data={
        "name_en": "Sunrise trek",
        "description_en": "a" * EXPERIENCE_DESCRIPTION_MAX_LENGTH,
        "description_id": "b" * EXPERIENCE_DESCRIPTION_MAX_LENGTH,
        "commission_percent": "10",
    })

    assert "description_en" not in form.errors
    assert "description_id" not in form.errors

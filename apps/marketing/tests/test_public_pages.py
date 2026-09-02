"""The public villa page and its booking form.

Two things are being defended here above all else, and they are why this file
is longer than the view it tests:

  1. Nothing unpublished is reachable, in any of the three ways a villa can be
     unpublished, plus a switched-off operator.
  2. Nothing private reaches the page - not the street address, not another
     operator's villa, not a guest or a booking.
"""

from datetime import date, timedelta

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import translation

from apps.bookings.models import Booking
from apps.marketing.models import BookingEnquiry, Experience
from apps.villas.models import Amenity, RoomCategory, Villa, VillaPhoto


@pytest.fixture(autouse=True)
def put_the_language_back():
    """Rendering an /id/ page leaves Indonesian active for the whole thread -
    LocaleMiddleware switches it on and nothing switches it off again once the
    response is done. Without this, the first Indonesian test in here quietly
    puts every test that runs afterwards - in any app - into Indonesian, and
    they fail on English strings they never went near.

    Scoped to this module, since this is the only place that changes language.
    """
    yield
    translation.activate(settings.LANGUAGE_CODE)


@pytest.fixture
def published_villa(org):
    """A villa as a visitor would find it: listed, live, not a draft, and with
    one room type that has a price and a two-night minimum.
    """
    villa = Villa.objects.create(
        organization=org, name="Villa Lumbung", slug="lumbung",
        area="Canggu", address="Jalan Pantai Batu Bolong 88, Canggu",
        description_en="Three bedrooms opening onto a shared pool.",
        description_id="Tiga kamar tidur menghadap kolam renang bersama.",
        is_listed_publicly=True,
    )
    category = villa.room_categories.first()
    category.nightly_rate = 2_500_000
    category.minimum_nights = 2
    category.max_guests = 4
    category.save()
    pool = Amenity.objects.create(name_en="Pool", name_id="Kolam renang")
    category.amenities.add(pool)
    return villa


# Reversed under English on purpose. The active language is thread-local and
# outlives a test, so a bare reverse() here would come back already prefixed
# with /id/ once any test above has rendered an Indonesian page - and the
# Indonesian tests below prepend /id/ themselves.
def page_url(villa, org_slug=None):
    with translation.override("en"):
        return reverse("marketing:villa_page", kwargs={
            "org": org_slug or villa.organization.slug, "villa": villa.slug,
        })


def book_url(villa):
    with translation.override("en"):
        return reverse("marketing:book", kwargs={
            "org": villa.organization.slug, "villa": villa.slug,
        })


# ---- who can be seen at all ------------------------------------------------

def test_published_villa_renders_with_its_rooms_and_amenities(client, published_villa):
    response = client.get(page_url(published_villa))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Villa Lumbung" in body
    assert "Canggu" in body
    assert "Pool" in body
    assert "Rp 2.500.000" in body


def test_a_villa_nobody_chose_to_list_is_not_there(client, published_villa):
    published_villa.is_listed_publicly = False
    published_villa.save()

    assert client.get(page_url(published_villa)).status_code == 404


def test_a_half_finished_villa_is_not_there(client, published_villa):
    published_villa.is_draft = True
    published_villa.save()

    assert client.get(page_url(published_villa)).status_code == 404


def test_a_removed_villa_is_not_there(client, published_villa):
    published_villa.is_active = False
    published_villa.save()

    assert client.get(page_url(published_villa)).status_code == 404


def test_a_switched_off_operators_villa_is_not_there(client, published_villa, org):
    org.is_active = False
    org.save()

    assert client.get(page_url(published_villa)).status_code == 404


def test_a_villa_is_not_reachable_under_another_operators_slug(
    client, published_villa, other_org
):
    """The single most important check in this file. There is no signed-in user
    on a public page, so the org slug in the URL is the whole tenant boundary.
    """
    response = client.get(page_url(published_villa, org_slug=other_org.slug))

    assert response.status_code == 404


def test_one_operators_villa_never_appears_on_anothers_page(client, published_villa, other_org):
    theirs = Villa.objects.create(
        organization=other_org, name="Villa Rahasia", slug="rahasia", is_listed_publicly=True,
    )
    response = client.get(page_url(published_villa))

    assert theirs.name not in response.content.decode()


# ---- what may not leak -----------------------------------------------------

def test_the_street_address_is_never_on_the_page(client, published_villa):
    response = client.get(page_url(published_villa))

    assert "Jalan Pantai Batu Bolong" not in response.content.decode()


def test_no_guest_or_booking_reaches_the_page(client, published_villa, guest):
    Booking.objects.create(
        organization=published_villa.organization, villa=published_villa, guest=guest,
        check_in=date.today() + timedelta(days=5), check_out=date.today() + timedelta(days=8),
    )
    body = client.get(page_url(published_villa)).content.decode()

    assert guest.full_name not in body
    assert guest.email not in body


def test_the_template_gets_values_not_a_villa_it_could_walk(client, published_villa):
    """The context carries plain fields. A Villa instance in there would let a
    future template line reach villa.bookings or villa.organization.memberships.
    """
    response = client.get(page_url(published_villa))
    context = response.context

    assert context["villa_name"] == "Villa Lumbung"
    assert not isinstance(context.get("villa"), Villa)
    assert "villa" not in context or context["villa"] is None


# ---- both languages --------------------------------------------------------

def test_the_page_renders_in_english(client, published_villa):
    response = client.get(page_url(published_villa))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Three bedrooms opening onto a shared pool." in body
    assert "About this villa" in body


def test_the_page_renders_in_indonesian(client, published_villa):
    response = client.get(f"/id{page_url(published_villa)}")
    body = response.content.decode()

    assert response.status_code == 200
    assert 'lang="id"' in body
    # The operator's own Indonesian text, not the English one.
    assert "Tiga kamar tidur menghadap kolam renang bersama." in body
    assert "Kolam renang" in body


def test_indonesian_falls_back_to_english_when_a_field_is_empty(client, published_villa):
    published_villa.description_id = ""
    published_villa.save()

    body = client.get(f"/id{page_url(published_villa)}").content.decode()

    assert "Three bedrooms opening onto a shared pool." in body


# ---- a villa with almost nothing on it -------------------------------------

def test_a_villa_with_no_description_photos_or_experiences_still_renders(client, org):
    bare = Villa.objects.create(
        organization=org, name="Villa Kosong", slug="kosong", is_listed_publicly=True,
    )
    response = client.get(page_url(bare))

    assert response.status_code == 200
    assert "Villa Kosong" in response.content.decode()
    # The sections with no data behind them are absent, not empty-headed.
    assert "About this villa" not in response.content.decode()


def test_only_this_villas_experiences_are_shown(client, published_villa, org):
    mine = Experience.objects.create(organization=org, name_en="Sunrise surf lesson")
    mine.villas.add(published_villa)
    Experience.objects.create(organization=org, name_en="Somebody else's tour")

    body = client.get(page_url(published_villa)).content.decode()

    assert "Sunrise surf lesson" in body
    assert "Somebody else's tour" not in body


def test_an_experience_that_was_switched_off_is_not_shown(client, published_villa, org):
    off = Experience.objects.create(
        organization=org, name_en="Cancelled cooking class", is_active=False,
    )
    off.villas.add(published_villa)

    assert "Cancelled cooking class" not in client.get(page_url(published_villa)).content.decode()


# ---- asking to book --------------------------------------------------------

def enquiry_data(**overrides):
    data = {
        "check_in": (date.today() + timedelta(days=10)).isoformat(),
        "check_out": (date.today() + timedelta(days=14)).isoformat(),
        "guest_count": 2,
        "guest_name": "Sari",
        "guest_email": "sari@example.com",
        "guest_phone": "",
        "message": "",
        "room_category": "",
    }
    data.update(overrides)
    return data


def test_a_good_request_is_recorded_and_confirmed(client, published_villa):
    response = client.post(book_url(published_villa), enquiry_data())

    assert response.status_code == 200
    enquiry = BookingEnquiry.objects.get()
    assert enquiry.villa == published_villa
    assert enquiry.organization == published_villa.organization
    assert enquiry.guest_name == "Sari"
    # 4 nights at 2.5m.
    assert enquiry.quoted_total == 10_000_000


def test_asking_to_book_never_creates_a_booking(client, published_villa):
    """CLAUDE.md rule 5: nothing public writes to live inventory."""
    client.post(book_url(published_villa), enquiry_data())

    assert Booking.objects.count() == 0


def test_a_stay_shorter_than_the_minimum_is_refused(client, published_villa):
    response = client.post(book_url(published_villa), enquiry_data(
        check_in=(date.today() + timedelta(days=10)).isoformat(),
        check_out=(date.today() + timedelta(days=11)).isoformat(),
    ))

    assert response.status_code == 400
    assert BookingEnquiry.objects.count() == 0
    assert "2 nights" in response.content.decode()


def test_dates_that_are_already_booked_are_refused(client, published_villa, guest):
    room = published_villa.rooms.first()
    Booking.objects.create(
        organization=published_villa.organization, villa=published_villa, room=room, guest=guest,
        check_in=date.today() + timedelta(days=9), check_out=date.today() + timedelta(days=15),
    )

    response = client.post(book_url(published_villa), enquiry_data())

    assert response.status_code == 400
    assert BookingEnquiry.objects.count() == 0
    assert "not available" in response.content.decode()


def test_a_cancelled_booking_does_not_block_the_dates(client, published_villa, guest):
    room = published_villa.rooms.first()
    Booking.objects.create(
        organization=published_villa.organization, villa=published_villa, room=room, guest=guest,
        check_in=date.today() + timedelta(days=9), check_out=date.today() + timedelta(days=15),
        status=Booking.Status.CANCELLED,
    )

    client.post(book_url(published_villa), enquiry_data())

    assert BookingEnquiry.objects.count() == 1


def test_a_date_in_the_past_is_refused(client, published_villa):
    response = client.post(book_url(published_villa), enquiry_data(
        check_in=(date.today() - timedelta(days=2)).isoformat(),
        check_out=(date.today() + timedelta(days=4)).isoformat(),
    ))

    assert response.status_code == 400
    assert BookingEnquiry.objects.count() == 0


def test_more_guests_than_the_rooms_sleep_is_refused(client, published_villa):
    response = client.post(book_url(published_villa), enquiry_data(guest_count=12))

    assert response.status_code == 400
    assert BookingEnquiry.objects.count() == 0


def test_no_way_to_reply_is_refused(client, published_villa):
    response = client.post(book_url(published_villa), enquiry_data(guest_email="", guest_phone=""))

    assert response.status_code == 400
    assert BookingEnquiry.objects.count() == 0


def test_a_room_type_from_another_villa_is_refused(client, published_villa, other_org):
    theirs = Villa.objects.create(organization=other_org, name="Theirs", slug="theirs")
    their_category = RoomCategory.objects.filter(villa=theirs).first()

    response = client.post(
        book_url(published_villa), enquiry_data(room_category=their_category.pk)
    )

    assert response.status_code == 400
    assert BookingEnquiry.objects.count() == 0


def test_you_cannot_book_an_unlisted_villa(client, published_villa):
    published_villa.is_listed_publicly = False
    published_villa.save()

    response = client.post(book_url(published_villa), enquiry_data())

    assert response.status_code == 404
    assert BookingEnquiry.objects.count() == 0


def test_you_cannot_book_a_villa_under_another_operators_slug(
    client, published_villa, other_org
):
    url = reverse("marketing:book", kwargs={
        "org": other_org.slug, "villa": published_villa.slug,
    })
    response = client.post(url, enquiry_data())

    assert response.status_code == 404
    assert BookingEnquiry.objects.count() == 0


# ---- photos ----------------------------------------------------------------

def a_real_webp(name="cover.webp"):
    """A genuine 2-pixel WebP, so the resizing in apps.villas.images runs for
    real rather than against a stub that would hide a breakage in it.
    """
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (1200, 800), "teal").save(buffer, format="WEBP")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/webp")


def test_the_cover_photo_is_rendered_with_a_srcset(client, published_villa):
    VillaPhoto.objects.create(
        organization=published_villa.organization, villa=published_villa,
        image=a_real_webp(), is_cover=True, caption_en="The pool at dusk",
    )
    body = client.get(page_url(published_villa)).content.decode()

    assert "The pool at dusk" in body
    assert "srcset" in body
    # Every size offered is WebP - see CLAUDE.md, no silent format fallback.
    assert ".webp" in body
    assert "480w" in body and "960w" in body


def test_a_photo_the_operator_has_not_saved_yet_is_not_published(client, published_villa):
    VillaPhoto.objects.create(
        organization=published_villa.organization, villa=published_villa,
        image=a_real_webp("staged.webp"), caption_en="Not saved yet", is_pending=True,
    )
    VillaPhoto.objects.create(
        organization=published_villa.organization, villa=published_villa,
        image=a_real_webp("removed.webp"), caption_en="Being taken off", pending_delete=True,
    )
    body = client.get(page_url(published_villa)).content.decode()

    assert "Not saved yet" not in body
    assert "Being taken off" not in body


def test_the_cover_photo_is_offered_to_whatsapp_as_an_open_graph_image(client, published_villa):
    VillaPhoto.objects.create(
        organization=published_villa.organization, villa=published_villa,
        image=a_real_webp(), is_cover=True,
    )
    body = client.get(page_url(published_villa)).content.decode()

    assert 'property="og:image"' in body
    assert 'content="http://testserver/media/' in body


def test_the_indonesian_page_uses_the_indonesian_interface_strings(client, published_villa):
    """Not just that the page renders under /id/, but that the new strings
    really made it into the catalogue - an untranslated msgid falls back to
    English silently, which is exactly the failure worth catching here.
    """
    body = client.get(f"/id{page_url(published_villa)}").content.decode()

    assert "Ajukan pemesanan" in body          # the Book button
    assert "Aktivitas di sekitar" not in body  # no experiences on this villa
    assert "Alamat lengkap dibagikan setelah pemesanan." in body


def test_an_unavailable_answer_is_given_in_indonesian(client, published_villa, guest):
    room = published_villa.rooms.first()
    Booking.objects.create(
        organization=published_villa.organization, villa=published_villa, room=room, guest=guest,
        check_in=date.today() + timedelta(days=9), check_out=date.today() + timedelta(days=15),
    )
    response = client.post(f"/id{book_url(published_villa)}", enquiry_data())

    assert response.status_code == 400
    assert "Tanggal ini tidak tersedia" in response.content.decode()

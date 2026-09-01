"""Fills the database with realistic, connected demo data.

Point of this command: let a person browse Django admin and actually feel the
shape of the schema - a returning guest, an overdue police report, a villa
whose SLF already expired, a WhatsApp message that failed because its
template wasn't approved yet. Every row exists to make one part of the design
visible, not just to pad table counts.

Three organizations get created - two small ones on opposite sync tiers, so
the premium/basic difference (feature honesty rule in CLAUDE.md) is visible in
the data itself, not just in theory, plus one large one for the real account
this project is built for:

  - Canggu Coastal Villas  (premium / Beds24)  - full guest detail everywhere
  - Ubud Green Retreats    (basic / iCal)      - mostly nameless, dates-only
                                                  bookings, exactly as a real
                                                  calendar feed would produce
  - Bali Horizon Villas    (premium / Beds24)  - REAL_OWNER_EMAIL is made its
                                                  Owner, with a much bigger,
                                                  bulk-generated portfolio to
                                                  browse - many villas,
                                                  guests and bookings rather
                                                  than a handful of examples

Safe to re-run: without --flush it refuses to touch existing demo data;
with --flush it deletes all three organizations (which cascades to everything
hanging off them) and rebuilds from scratch. REAL_OWNER_EMAIL's own User
account is never touched - only the Organization/Membership linking it to
demo data - so its password and superuser status survive every re-run.
"""

import random
from datetime import date, datetime
from datetime import time as dt_time
from io import BytesIO

from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from PIL import Image, ImageDraw

from apps.accounts.models import User
from apps.bookings.models import Booking, BookingPayment
from apps.compliance.models import ComplianceDocument, ComplianceDocumentType, PoliceReport
from apps.core.calendar import BaliHoliday
from apps.guests.models import Guest, GuestActivity, GuestFeedback, GuestRequest
from apps.guests.services import find_or_create_guest
from apps.marketing.models import Experience, RateSnapshot
from apps.messaging.models import Conversation, InboundMessage, MessageTemplate, OutboundMessage
from apps.organizations.models import Membership, Organization
from apps.organizations.permissions import MANAGER_GROUP, STAFF_GROUP
from apps.reporting.fx import ExchangeRate
from apps.sync.models import RawPayload, SyncAccount, SyncRun
from apps.villas.models import Amenity, Room, Villa, VillaPhoto, create_room_type

DEMO_ORG_SLUGS = ["canggu-coastal", "ubud-green", "bali-horizon"]
DEMO_PASSWORD = "DemoPass123!"
REAL_OWNER_EMAIL = "alirezakeyvan06@gmail.com"

FIRST_NAMES = [
    "Oliver", "Emma", "Liam", "Sophia", "Noah", "Isabella", "Ethan", "Mia",
    "Lucas", "Charlotte", "Mason", "Amelia", "Daniel", "Evelyn", "Matthew",
    "Abigail", "Henry", "Emily", "Sebastian", "Elizabeth", "Jack", "Sofia",
    "Owen", "Avery", "Leo", "Ella", "Gabriel", "Scarlett", "Felix", "Nadia",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson",
    "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
    "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez",
    "Lewis", "Robinson", "Walker",
]
NATIONALITIES = [
    "AU", "US", "GB", "DE", "FR", "NL", "RU", "JP", "KR", "SG",
    "CN", "IN", "CA", "ES", "IT", "SE", "CH", "BR", "MX", "ZA",
]

BIG_VILLAS = [
    ("Villa Kilauea Sunrise", "Uluwatu", Villa.PropertyType.VILLA, 5, 5, 10),
    ("Villa Sawah Terrace", "Ubud", Villa.PropertyType.VILLA, 3, 3, 6),
    ("Bamboo Loft Canggu", "Canggu", Villa.PropertyType.GUESTHOUSE, 2, 1, 4),
    ("Villa Laguna Biru", "Sanur", Villa.PropertyType.VILLA, 4, 4, 8),
    ("Seminyak Sky Residence", "Seminyak", Villa.PropertyType.APARTMENT, 2, 2, 4),
    ("Villa Cempaka", "Jimbaran", Villa.PropertyType.VILLA, 3, 3, 6),
    ("The Nomad House", "Canggu", Villa.PropertyType.HOUSE, 4, 3, 8),
    ("Villa Kelapa Tinggi", "Uluwatu", Villa.PropertyType.VILLA, 6, 6, 12),
]
PHOTO_COLORS = [
    (210, 140, 90), (80, 120, 160), (120, 150, 90), (190, 100, 100),
    (100, 160, 150), (170, 130, 200), (140, 170, 90), (90, 100, 150),
]


def _placeholder_photo(label: str, color: tuple[int, int, int]) -> ContentFile:
    """A small solid-color WebP standing in for a real villa photo.

    Generated as WebP because that is the only format this project serves
    guest-facing images in - see CLAUDE.md - and demo data should not model a
    shortcut real uploads never get to take.
    """
    image = Image.new("RGB", (800, 600), color=color)
    draw = ImageDraw.Draw(image)
    draw.text((40, 270), label, fill=(255, 255, 255))
    buffer = BytesIO()
    image.save(buffer, format="WEBP", quality=80)
    slug = label.lower().replace(" ", "-")
    return ContentFile(buffer.getvalue(), name=f"{slug}.webp")


class Command(BaseCommand):
    help = "Populate the database with realistic, interconnected demo data for browsing in admin."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing demo organizations (and everything under them) before recreating.",
        )

    def handle(self, *args, **options):
        existing = Organization.objects.filter(slug__in=DEMO_ORG_SLUGS)
        if existing.exists():
            if not options["flush"]:
                self.stdout.write(self.style.WARNING(
                    "Demo organizations already exist. Re-run with --flush to wipe and rebuild them."
                ))
                return
            self.stdout.write("Removing existing demo data...")
            # Booking.villa is PROTECT on purpose - see apps/bookings/models.py -
            # so bookings have to go before the organization cascade can reach
            # villas. ComplianceDocument.document_type is PROTECT too (never
            # let a type disappear out from under a document that uses it),
            # which blocks the org cascade from reaching a document's own
            # (possibly org-scoped) ComplianceDocumentType - same fix, go first.
            Booking.objects.filter(organization__in=existing).delete()
            ComplianceDocument.objects.filter(organization__in=existing).delete()
            existing.delete()

        self.today = timezone.localdate()
        self.now = timezone.now()

        self.stdout.write("Creating organizations, users and villas...")
        self._build_organizations()
        self._build_users()
        self._build_amenities()
        self._build_villas()

        self.stdout.write("Creating guests...")
        self._build_guests()

        self.stdout.write("Creating bookings and payments...")
        self._build_exchange_rates()
        self._build_bookings()
        self._recalculate_guest_stay_counts()

        self.stdout.write("Creating guest activity, requests and feedback...")
        self._build_guest_activity()

        self.stdout.write("Creating sync accounts and run history...")
        self._build_sync()

        self.stdout.write("Creating compliance documents and police reports...")
        self._build_compliance()

        self.stdout.write("Creating WhatsApp templates and messages...")
        self._build_messaging()

        self.stdout.write("Creating experiences and rate snapshots...")
        self._build_marketing()

        self.stdout.write("Creating Bali holiday calendar entries...")
        self._build_holidays()

        self.stdout.write(f"Creating a large portfolio owned by {REAL_OWNER_EMAIL}...")
        self.rng = random.Random(20260827)
        self._build_big_organization()

        self._print_summary()

    # ------------------------------------------------------------ organizations

    def _build_organizations(self):
        self.canggu, _ = Organization.objects.get_or_create(
            slug="canggu-coastal",
            defaults=dict(
                name="Canggu Coastal Villas",
                sync_tier=Organization.SyncTier.PREMIUM,
                default_currency="IDR",
                whatsapp_number="+622112340001",
            ),
        )
        self.ubud, _ = Organization.objects.get_or_create(
            slug="ubud-green",
            defaults=dict(
                name="Ubud Green Retreats",
                sync_tier=Organization.SyncTier.BASIC,
                default_currency="IDR",
                whatsapp_number="+622112340002",
            ),
        )

    def _build_users(self):
        def user(email, full_name, phone, language="en"):
            u, created = User.objects.get_or_create(
                email=email, defaults=dict(full_name=full_name, phone=phone, preferred_language=language)
            )
            if created:
                u.set_password(DEMO_PASSWORD)
                u.save()
            return u

        self.owner1 = user("budi.owner@canggucoastal.example", "Budi Santoso", "+6281111000001", "id")
        self.manager1 = user("sarah.manager@canggucoastal.example", "Sarah Wijaya", "+6281111000002")
        self.staff1 = user("made.staff@canggucoastal.example", "Made Arta", "+6281111000003", "id")
        self.staff2 = user("kadek.staff@canggucoastal.example", "Kadek Putri", "+6281111000004", "id")
        self.owner2 = user("john.owner@ubudgreen.example", "John Sutherland", "+6281222000001")
        self.staff3 = user("wayan.staff@ubudgreen.example", "Wayan Sujana", "+6281222000002", "id")

        manager_group, _created = Group.objects.get_or_create(name=MANAGER_GROUP)
        staff_group, _created = Group.objects.get_or_create(name=STAFF_GROUP)

        Membership.objects.get_or_create(user=self.owner1, organization=self.canggu)
        Membership.objects.get_or_create(user=self.manager1, organization=self.canggu)
        m1, _ = Membership.objects.get_or_create(user=self.staff1, organization=self.canggu)
        m2, _ = Membership.objects.get_or_create(user=self.staff2, organization=self.canggu)
        Membership.objects.get_or_create(user=self.owner2, organization=self.ubud)
        Membership.objects.get_or_create(user=self.staff3, organization=self.ubud)

        self.owner1.groups.add(manager_group)
        self.manager1.groups.add(manager_group)
        self.staff1.groups.add(staff_group)
        self.staff2.groups.add(staff_group)
        self.owner2.groups.add(manager_group)
        self.staff3.groups.add(staff_group)
        self._staff_membership_villas = (m1, m2)  # villas assigned after villas exist

    # ------------------------------------------------------------ villas

    def _build_amenities(self):
        """The shared list, matching what migration 0011 already put there.

        organization=None on both sides of the lookup on purpose: these are
        the ones everybody gets, and an operator's own custom amenity must
        never be picked up here and handed to somebody else's villa.
        """
        pairs = [
            ("Pool", "Kolam renang"),
            ("WiFi", "WiFi"),
            ("Air conditioning", "Pendingin ruangan"),
            ("Full kitchen", "Dapur lengkap"),
            ("Free parking", "Parkir gratis"),
            ("Rice field view", "Pemandangan sawah"),
            ("Private garden", "Taman pribadi"),
            ("Daily housekeeping", "Bersih-bersih harian"),
            ("Electricity included", "Listrik sudah termasuk"),
        ]
        self.amenities = {
            en: Amenity.objects.get_or_create(
                name_en=en, organization=None, defaults={"name_id": idn},
            )[0]
            for en, idn in pairs
        }

    def _build_villas(self):
        def villa(org, name, slug, area, bedrooms, max_guests, public, desc_en, desc_id, amenity_names):
            v, _ = Villa.objects.get_or_create(
                organization=org, slug=slug,
                defaults=dict(
                    name=name, area=area, bedrooms=bedrooms,
                    is_listed_publicly=public, description_en=desc_en, description_id=desc_id,
                ),
            )
            # How many guests a room sleeps, and what it comes with, live on
            # the room type - so they go on the one the villa started with.
            category = v.room_categories.first()
            if category is not None:
                category.max_guests = max(max_guests // max(bedrooms, 1), 1)
                category.save(update_fields=["max_guests"])
                category.amenities.set([self.amenities[a] for a in amenity_names])
            return v

        self.villa_sunset = villa(
            self.canggu, "Villa Sunset Canggu", "villa-sunset-canggu", "Canggu", 4, 8, True,
            "A four-bedroom beachside villa two minutes from Batu Bolong beach, "
            "with an infinity pool facing the sunset.",
            "Villa pantai dengan empat kamar tidur, dua menit dari Pantai Batu Bolong, "
            "dengan kolam infinity menghadap matahari terbenam.",
            ["Pool", "WiFi", "Air conditioning", "Full kitchen", "Free parking", "Daily housekeeping"],
        )
        self.villa_ombak = villa(
            self.canggu, "Villa Ombak Biru", "villa-ombak-biru", "Canggu", 2, 4, True,
            "A cosy two-bedroom villa in Berawa with a private plunge pool, "
            "walking distance to cafes and surf breaks.",
            "Villa dua kamar tidur yang nyaman di Berawa dengan kolam pribadi, "
            "jalan kaki ke kafe dan spot surfing.",
            ["Pool", "WiFi", "Air conditioning", "Free parking"],
        )
        self.villa_kelapa = villa(
            self.canggu, "Villa Kelapa Muda", "villa-kelapa-muda", "Berawa", 3, 6, False,
            "Three-bedroom family villa set back from the road for quiet, "
            "with a shared garden and rooftop deck.",
            "Villa keluarga tiga kamar tidur, tenang karena jauh dari jalan raya, "
            "dengan taman bersama dan rooftop deck.",
            ["Pool", "WiFi", "Full kitchen", "Private garden"],
        )
        self.villa_hutan = villa(
            self.ubud, "Villa Hutan Hijau", "villa-hutan-hijau", "Ubud", 2, 4, False,
            "Two-bedroom jungle-facing villa fifteen minutes from central Ubud.",
            "Villa dua kamar tidur menghadap hutan, lima belas menit dari pusat Ubud.",
            ["Pool", "WiFi", "Rice field view", "Daily housekeeping"],
        )
        self.villa_padi = villa(
            self.ubud, "Villa Padi Emas", "villa-padi-emas", "Tegallalang", 3, 6, False,
            "Three-bedroom villa overlooking the Tegallalang rice terraces.",
            "Villa tiga kamar tidur dengan pemandangan terasering sawah Tegallalang.",
            ["Pool", "WiFi", "Rice field view", "Private garden"],
        )

        # Staff assigned to specific villas - see Membership.villas.
        m1, m2 = self._staff_membership_villas
        m1.villas.add(self.villa_sunset)
        m2.villas.add(self.villa_ombak)

        for villa_obj, color in [
            (self.villa_sunset, (235, 150, 80)),
            (self.villa_ombak, (70, 130, 180)),
            (self.villa_kelapa, (100, 160, 90)),
            (self.villa_hutan, (60, 110, 70)),
            (self.villa_padi, (200, 180, 60)),
        ]:
            if not villa_obj.photos.live().exists():
                VillaPhoto.objects.create(
                    organization=villa_obj.organization, villa=villa_obj,
                    image=_placeholder_photo(villa_obj.name, color),
                    caption_en=f"{villa_obj.name} - main view",
                    caption_id=f"{villa_obj.name} - tampak utama",
                    is_cover=True,
                )

    # ------------------------------------------------------------ guests

    def _build_guests(self):
        def guest(org, name, email, phone, nationality):
            return find_or_create_guest(org, full_name=name, email=email, phone=phone, nationality=nationality)

        self.anna = guest(self.canggu, "Anna Petrova", "anna.petrova@example.com", "+79161234567", "RU")
        self.james = guest(self.canggu, "James Whitfield", "james.whitfield@example.com", "+61412345678", "AU")
        self.yuki = guest(self.canggu, "Yuki Tanaka", "yuki.tanaka@example.com", "+819012345678", "JP")
        self.emma = guest(self.canggu, "Emma Muller", "emma.muller@example.com", "+491701234567", "DE")
        self.lotte = guest(self.canggu, "Lotte de Vries", "lotte.devries@example.com", "+31612345678", "NL")

        self.sophie = guest(self.ubud, "Sophie Laurent", "sophie.laurent@example.com", "+33612345678", "FR")
        self.mark = guest(self.ubud, "Mark Johnson", "mark.johnson@example.com", "+14155552671", "US")
        self.rina = guest(self.ubud, "Rina Kartika", "rina.kartika@example.com", "+6281234509876", "ID")

    # ------------------------------------------------------------ money

    def _build_exchange_rates(self):
        """Display-time conversion rates - see apps/reporting/fx.py.

        Backdated so any stored-currency amount from "today" resolves.
        """
        as_of = self.today - timezone.timedelta(days=60)
        for currency, rate in [("USD", "15800"), ("AUD", "10400"), ("EUR", "17200"), ("JPY", "105")]:
            ExchangeRate.objects.get_or_create(
                base_currency=currency, quote_currency="IDR", effective_on=as_of,
                defaults={"rate": rate},
            )

    # ------------------------------------------------------------ bookings

    def _build_bookings(self):
        d = timezone.timedelta
        room_index: dict[int, int] = {}

        def booking(org, villa, external_id, channel, guest, check_in, check_out,
                    source_detail, status=Booking.Status.CONFIRMED, guest_count=2, notes=""):
            # Round-robin across the villa's rooms (already provisioned when
            # the villa was created - see provision_starter_rooms) so bookings
            # spread across room rows on the calendar instead of piling onto
            # room 1. The calendar has no "unassigned" fallback row, so every
            # booking needs a real room to show up at all.
            rooms = list(villa.rooms.order_by("id"))
            i = room_index.get(villa.id, 0)
            room_index[villa.id] = i + 1
            obj, _ = Booking.objects.get_or_create(
                organization=org, external_id=external_id,
                defaults=dict(
                    villa=villa, room=rooms[i % len(rooms)], guest=guest,
                    check_in=check_in, check_out=check_out,
                    channel=channel, status=status, source_detail=source_detail,
                    guest_count=guest_count, notes=notes,
                    last_synced_at=self.now if source_detail == Booking.SourceDetail.FULL else None,
                ),
            )
            return obj

        FULL, DATES_ONLY, MANUAL = (
            Booking.SourceDetail.FULL, Booking.SourceDetail.DATES_ONLY, Booking.SourceDetail.MANUAL
        )

        # --- Canggu Coastal: premium tier, full guest detail throughout ---
        self.b_anna_past = booking(
            self.canggu, self.villa_sunset, "beds24-100234", Booking.Channel.AIRBNB,
            self.anna, self.today - d(days=10), self.today - d(days=3), FULL,
        )
        self.b_james_current = booking(
            self.canggu, self.villa_sunset, "beds24-100240", Booking.Channel.BOOKING_COM,
            self.james, self.today - d(days=1), self.today + d(days=4), FULL, guest_count=4,
        )
        self.b_yuki_upcoming = booking(
            self.canggu, self.villa_sunset, "beds24-100255", Booking.Channel.AIRBNB,
            self.yuki, self.today + d(days=7), self.today + d(days=12), FULL,
        )
        self.b_anna_direct = booking(
            self.canggu, self.villa_ombak, "beds24-100301", Booking.Channel.DIRECT,
            self.anna, self.today + d(days=20), self.today + d(days=25), FULL,
        )
        self.b_emma_past = booking(
            self.canggu, self.villa_ombak, "beds24-100310", Booking.Channel.WHATSAPP,
            self.emma, self.today - d(days=30), self.today - d(days=25), FULL,
        )
        booking(
            self.canggu, self.villa_ombak, "beds24-100320", Booking.Channel.AIRBNB,
            None, self.today + d(days=15), self.today + d(days=18), FULL,
            status=Booking.Status.CANCELLED, notes="Guest cancelled within the free window.",
        )
        self.b_lotte_upcoming = booking(
            self.canggu, self.villa_kelapa, "beds24-100400", Booking.Channel.AIRBNB,
            self.lotte, self.today + d(days=2), self.today + d(days=9), FULL,
        )

        # --- Ubud Green: basic tier, iCal feeds only know blocked dates ---
        booking(
            self.ubud, self.villa_hutan, "ical-airbnb-55901", Booking.Channel.AIRBNB,
            None, self.today - d(days=5), self.today - d(days=1), DATES_ONLY,
        )
        booking(
            self.ubud, self.villa_hutan, "ical-airbnb-55910", Booking.Channel.AIRBNB,
            None, self.today + d(days=3), self.today + d(days=6), DATES_ONLY,
            status=Booking.Status.BLOCKED, notes="Owner's personal use - blocked, not a guest stay.",
        )
        booking(
            self.ubud, self.villa_hutan, "ical-booking-77012", Booking.Channel.BOOKING_COM,
            None, self.today + d(days=10), self.today + d(days=14), DATES_ONLY,
        )
        self.b_sophie = booking(
            self.ubud, self.villa_hutan, "demo-manual-0001", Booking.Channel.WHATSAPP,
            self.sophie, self.today + d(days=1), self.today + d(days=5), MANUAL,
            notes="Guest messaged the owner directly on WhatsApp; entered by staff.",
        )
        booking(
            self.ubud, self.villa_padi, "ical-airbnb-55950", Booking.Channel.AIRBNB,
            None, self.today - d(days=2), self.today + d(days=2), DATES_ONLY,
        )
        self.b_mark = booking(
            self.ubud, self.villa_padi, "demo-manual-0002", Booking.Channel.DIRECT,
            self.mark, self.today + d(days=25), self.today + d(days=30), MANUAL,
        )
        self.b_rina = booking(
            self.ubud, self.villa_padi, "demo-manual-0003", Booking.Channel.DIRECT,
            self.rina, self.today + d(days=40), self.today + d(days=43), MANUAL,
        )

        self._build_rooms()
        self._build_payments()

    def _build_rooms(self):
        """Give two villas (one per org) nicely named, mixed-category rooms so
        the calendar's villa->room nesting shows real variety out of the box.

        Every villa already starts with one room per bedroom under a single
        room type (see apps.villas.models.provision_starter_rooms), so this
        renames those rooms in place rather than adding more - adding would
        push a villa's room count past the number it advertises on the villa
        list.
        """
        def name_rooms(villa, named):
            """Apply (name, type name) pairs to the villa's existing rooms, in
            order. Any room beyond the end of the list keeps its default name.
            Room types are per villa, so each one is looked up - and created
            if this villa doesn't have it yet - on its own villa.
            """
            types = {c.name: c for c in villa.room_categories.all()}
            for _name, type_name in named:
                if type_name not in types:
                    types[type_name] = create_room_type(villa, type_name, how_many=0)
            rooms = list(villa.rooms.order_by("id"))
            for room_obj, (name, type_name) in zip(rooms, named):
                room_obj.name = name
                room_obj.category = types.get(type_name)
                room_obj.save(update_fields=["name", "category"])
            return rooms

        sunset_rooms = name_rooms(self.villa_sunset, [
            ("Sunset 1", "Deluxe"),
            ("Sunset 2", "Deluxe"),
            ("Sunset 3", "Standard"),
        ])
        hutan_rooms = name_rooms(self.villa_hutan, [
            ("Hutan 1", "Standard"),
            ("Hutan 2", "Suite"),
        ])

        # Move these two onto named rooms for narrative flavor - they already
        # got a room at creation time (see _build_bookings), just not one of
        # the newly-renamed ones above.
        self.b_james_current.room = sunset_rooms[0]
        self.b_james_current.save(update_fields=["room"])
        self.b_sophie.room = hutan_rooms[0]
        self.b_sophie.save(update_fields=["room"])

    def _build_payments(self):
        def payment(booking_obj, kind, amount, currency, received_on=None, outstanding=False, stripe=""):
            return BookingPayment.objects.get_or_create(
                organization=booking_obj.organization, booking=booking_obj, kind=kind,
                amount=amount, currency=currency,
                defaults=dict(received_on=received_on, is_outstanding=outstanding, stripe_payment_intent=stripe),
            )

        payment(self.b_anna_past, BookingPayment.Kind.PAYOUT, "12500000.00", "IDR",
                received_on=self.b_anna_past.check_in)
        payment(self.b_james_current, BookingPayment.Kind.PAYOUT, "850.00", "AUD",
                received_on=self.b_james_current.check_in)
        payment(self.b_yuki_upcoming, BookingPayment.Kind.PAYOUT, "95000.00", "JPY", outstanding=True)
        payment(self.b_anna_direct, BookingPayment.Kind.DIRECT, "620.00", "USD",
                stripe="pi_demo_1A2b3C4d5E6f")
        payment(self.b_emma_past, BookingPayment.Kind.PAYOUT, "480.00", "EUR",
                received_on=self.b_emma_past.check_in)
        payment(self.b_lotte_upcoming, BookingPayment.Kind.PAYOUT, "1400.00", "USD", outstanding=True)
        payment(self.b_sophie, BookingPayment.Kind.DEPOSIT, "150.00", "EUR",
                received_on=self.today)
        payment(self.b_sophie, BookingPayment.Kind.DIRECT, "350.00", "EUR", outstanding=True)
        payment(self.b_mark, BookingPayment.Kind.DIRECT, "900.00", "USD", received_on=self.today)
        payment(self.b_rina, BookingPayment.Kind.DIRECT, "4500000.00", "IDR", received_on=self.today)

    def _recalculate_guest_stay_counts(self):
        """Stand-in for the recalculation a Celery job should do when a
        booking closes - see the Guest model docstring. Seed data sets these
        directly so the guest list doesn't show every returning guest as new.
        """
        for g in Guest.objects.filter(organization__in=[self.canggu, self.ubud]):
            bookings = Booking.objects.filter(guest=g).exclude(status=Booking.Status.CANCELLED)
            if not bookings.exists():
                continue
            g.total_stays = bookings.count()
            g.first_seen = min(b.check_in for b in bookings)
            g.last_seen = max(b.check_in for b in bookings)
            g.save(update_fields=["total_stays", "first_seen", "last_seen"])

    # ------------------------------------------------------------ guest activity

    def _activity(self, guest, kind, *, booking=None, villa=None, subject="", detail=None, occurred_at=None):
        """Mirrors apps.guests.services.log_activity but allows a backdated
        timestamp, so demo activity lines up with when it would really have
        happened during a past or upcoming stay.
        """
        return GuestActivity.objects.create(
            organization=guest.organization, guest=guest,
            booking=booking, villa=villa or (booking.villa if booking else None),
            kind=kind, subject=subject, detail=detail or {},
            occurred_at=occurred_at or self.now,
        )

    def _build_guest_activity(self):
        d = timezone.timedelta
        A = GuestActivity.Kind

        self._activity(self.anna, A.PORTAL_OPENED, booking=self.b_anna_past,
                        occurred_at=self._at(self.b_anna_past.check_in))
        self._activity(self.anna, A.EXPERIENCE_BOOKED, booking=self.b_anna_past,
                        subject="Monkey Forest tour",
                        detail={"price": "450000", "currency": "IDR", "party_size": 2},
                        occurred_at=self._at(self.b_anna_past.check_in + d(days=1)))
        self._activity(self.anna, A.EXPERIENCE_VIEWED, booking=self.b_anna_direct,
                        subject="Balinese cooking class", occurred_at=self.now - d(days=2))

        self._activity(self.james, A.PORTAL_OPENED, booking=self.b_james_current,
                        occurred_at=self._at(self.b_james_current.check_in))
        self._activity(self.james, A.REQUEST_MADE, booking=self.b_james_current,
                        subject="Airport transfer", occurred_at=self.now - d(hours=2))

        self._activity(self.yuki, A.PORTAL_OPENED, booking=self.b_yuki_upcoming, occurred_at=self.now)
        self._activity(self.yuki, A.EXPERIENCE_VIEWED, booking=self.b_yuki_upcoming,
                        subject="Sunrise trekking Mount Batur", occurred_at=self.now)

        self._activity(self.emma, A.REQUEST_MADE, booking=self.b_emma_past,
                        subject="Air conditioning repair",
                        occurred_at=self._at(self.b_emma_past.check_in + d(days=1)))
        self._activity(self.emma, A.FEEDBACK_GIVEN, booking=self.b_emma_past,
                        occurred_at=self._at(self.b_emma_past.check_out - d(days=1)))

        self._activity(self.lotte, A.PORTAL_OPENED, booking=self.b_lotte_upcoming, occurred_at=self.now)
        self._activity(self.lotte, A.EXPERIENCE_BOOKED, booking=self.b_lotte_upcoming,
                        subject="Private chef - seafood BBQ",
                        detail={"price": "1200000", "currency": "IDR", "party_size": 4},
                        occurred_at=self.now)

        self._activity(self.sophie, A.REQUEST_MADE, booking=self.b_sophie,
                        subject="Grocery stocking", occurred_at=self.now - d(hours=6))
        self._activity(self.mark, A.EXPERIENCE_VIEWED, booking=self.b_mark,
                        subject="Balinese cooking class", occurred_at=self.now - d(days=1))

        self._build_requests_and_feedback()

    def _at(self, day: date) -> datetime:
        return timezone.make_aware(datetime.combine(day, dt_time(14, 0)))

    def _build_requests_and_feedback(self):
        GuestRequest.objects.get_or_create(
            booking=self.b_james_current, guest=self.james, kind=GuestRequest.Kind.TRANSFER,
            defaults=dict(
                organization=self.canggu,
                message="Need airport pickup tomorrow at 3pm, 4 people with luggage.",
                status=GuestRequest.Status.SEEN, assigned_to=self.staff1,
                notified_at=self.now - timezone.timedelta(hours=2),
            ),
        )
        GuestRequest.objects.get_or_create(
            booking=self.b_emma_past, guest=self.emma, kind=GuestRequest.Kind.REPAIR,
            defaults=dict(
                organization=self.canggu,
                message="AC in the master bedroom is not cooling.",
                status=GuestRequest.Status.DONE, assigned_to=self.staff2,
                notified_at=self._at(self.b_emma_past.check_in + timezone.timedelta(days=1)),
            ),
        )
        GuestRequest.objects.get_or_create(
            booking=self.b_lotte_upcoming, guest=self.lotte, kind=GuestRequest.Kind.CHEF,
            defaults=dict(
                organization=self.canggu,
                message="Seafood BBQ for 4 people on arrival night.",
                status=GuestRequest.Status.NEW,
            ),
        )
        GuestRequest.objects.get_or_create(
            booking=self.b_sophie, guest=self.sophie, kind=GuestRequest.Kind.GROCERIES,
            defaults=dict(
                organization=self.ubud,
                message="Please stock the fridge: eggs, milk, fruit, coffee.",
                status=GuestRequest.Status.NEW,
            ),
        )

        GuestFeedback.objects.get_or_create(
            booking=self.b_anna_past, guest=self.anna,
            defaults=dict(
                organization=self.canggu, rating=5,
                comment="Amazing stay, the pool area at sunset was perfect!",
            ),
        )
        GuestFeedback.objects.get_or_create(
            booking=self.b_emma_past, guest=self.emma,
            defaults=dict(
                organization=self.canggu, rating=2,
                comment="The AC issue made it hard to sleep for two nights before it got fixed.",
                escalated_to_owner=True,
            ),
        )

    # ------------------------------------------------------------ sync

    def _build_sync(self):
        beds24 = SyncAccount.objects.get_or_create(
            organization=self.canggu, provider=SyncAccount.Provider.BEDS24,
            defaults=dict(
                label="Beds24 - main account", beds24_property_id="45821",
                refresh_token="demo-refresh-token-do-not-use-in-production",
                last_success_at=self.now - timezone.timedelta(hours=2),
            ),
        )[0]
        hutan_airbnb = SyncAccount.objects.get_or_create(
            organization=self.ubud, provider=SyncAccount.Provider.ICAL, villa=self.villa_hutan,
            defaults=dict(
                label="Airbnb calendar - Villa Hutan Hijau", ical_channel="airbnb",
                ical_url="https://www.airbnb.com/calendar/ical/00000001.ics?s=demo",
                last_success_at=self.now - timezone.timedelta(hours=5),
            ),
        )[0]
        hutan_booking = SyncAccount.objects.get_or_create(
            organization=self.ubud, provider=SyncAccount.Provider.ICAL, villa=self.villa_hutan,
            ical_channel="booking_com",
            defaults=dict(
                label="Booking.com calendar - Villa Hutan Hijau",
                ical_url="https://admin.booking.com/ical/demo/00000099.ics",
                last_error="Feed returned 404 - check the URL is still valid in the extranet.",
            ),
        )[0]
        padi_booking = SyncAccount.objects.get_or_create(
            organization=self.ubud, provider=SyncAccount.Provider.ICAL, villa=self.villa_padi,
            defaults=dict(
                label="Booking.com calendar - Villa Padi Emas", ical_channel="booking_com",
                ical_url="https://admin.booking.com/ical/demo/00000002.ics",
                last_success_at=self.now - timezone.timedelta(hours=6),
            ),
        )[0]

        d = timezone.timedelta
        SyncRun.objects.get_or_create(
            organization=self.canggu, account=beds24, trigger=SyncRun.Trigger.WEBHOOK,
            result=SyncRun.Result.OK, bookings_created=1, bookings_updated=0,
            defaults=dict(message="New booking pushed by Beds24.", finished_at=self.now - d(hours=2)),
        )
        SyncRun.objects.get_or_create(
            organization=self.canggu, account=beds24, trigger=SyncRun.Trigger.SCHEDULED,
            result=SyncRun.Result.OK, bookings_created=0, bookings_updated=2,
            defaults=dict(message="Routine reconciliation - 2 bookings updated.", finished_at=self.now - d(hours=8)),
        )
        SyncRun.objects.get_or_create(
            organization=self.ubud, account=hutan_airbnb, trigger=SyncRun.Trigger.SCHEDULED,
            result=SyncRun.Result.OK, bookings_created=0, bookings_updated=1,
            defaults=dict(message="Feed refreshed, 1 date range updated.", finished_at=self.now - d(hours=5)),
        )
        SyncRun.objects.get_or_create(
            organization=self.ubud, account=hutan_booking, trigger=SyncRun.Trigger.SCHEDULED,
            result=SyncRun.Result.FAILED, bookings_created=0, bookings_updated=0,
            defaults=dict(message="Feed URL returned 404.", finished_at=self.now - d(hours=1)),
        )
        SyncRun.objects.get_or_create(
            organization=self.ubud, account=padi_booking, trigger=SyncRun.Trigger.SCHEDULED,
            result=SyncRun.Result.OK, bookings_created=1, bookings_updated=0,
            defaults=dict(message="Feed refreshed, 1 new block found.", finished_at=self.now - d(hours=6)),
        )

        RawPayload.objects.get_or_create(
            organization=self.canggu, account=beds24, endpoint="/bookings",
            defaults=dict(
                body={"bookId": "100240", "roomId": 4821, "guestName": "James Whitfield",
                      "arrival": str(self.b_james_current.check_in), "status": "confirmed"},
                processed_at=self.now - d(hours=2),
            ),
        )
        RawPayload.objects.get_or_create(
            organization=self.ubud, account=hutan_booking, endpoint="ical-fetch",
            defaults=dict(body={}, error="Could not parse VEVENT block: missing DTSTART."),
        )

    # ------------------------------------------------------------ compliance

    def _doc_type(self, name):
        # The migration that introduced ComplianceDocumentType already
        # created these 5 global types, so seeding just looks them up rather
        # than recreating them.
        return ComplianceDocumentType.objects.get(organization=None, name=name)

    def _build_compliance(self):
        def document(org, villa, doc_type, ref, expires_on, reminder_days=60):
            return ComplianceDocument.objects.get_or_create(
                organization=org, villa=villa, document_type=doc_type, reference_number=ref,
                defaults=dict(
                    file=ContentFile(b"%PDF-1.4 demo placeholder\n", name=f"{ref}.pdf"),
                    expires_on=expires_on, reminder_days=reminder_days,
                ),
            )[0]

        d = timezone.timedelta
        nib = self._doc_type("Business licence (NIB)")
        pbg = self._doc_type("Building approval (PBG)")
        slf = self._doc_type("Building safety certificate (SLF)")
        tax = self._doc_type("Tax registration")
        document(self.canggu, None, nib, "NIB-8120000123456", self.today + d(days=400))
        document(self.canggu, self.villa_sunset, pbg,
                 "PBG-DPMPTSP-2023-00456", self.today + d(days=20))  # needs attention soon
        document(self.canggu, self.villa_ombak, slf,
                 "SLF-2021-00987", self.today - d(days=15), reminder_days=90)  # already expired
        document(self.ubud, None, nib, "NIB-8120000998877", self.today + d(days=500))
        document(self.ubud, self.villa_hutan, tax, "NPWP-01.234.567.8-901.000", None)

        def police_report(booking, guest, deadline, status, marked_by=None, marked_at=None):
            return PoliceReport.objects.get_or_create(
                organization=booking.organization, booking=booking, guest=guest,
                defaults=dict(deadline=deadline, status=status, marked_done_by=marked_by, marked_done_at=marked_at),
            )

        police_report(
            self.b_anna_past, self.anna, self._at(self.b_anna_past.check_in) + d(hours=24),
            PoliceReport.Status.FILED, marked_by=self.staff1,
            marked_at=self._at(self.b_anna_past.check_in) + d(hours=20),
        )
        police_report(  # deliberately overdue - James checked in yesterday, nobody's filed it
            self.b_james_current, self.james, self.now - d(hours=3), PoliceReport.Status.NEEDED,
        )
        police_report(
            self.b_yuki_upcoming, self.yuki, self._at(self.b_yuki_upcoming.check_in) + d(hours=24),
            PoliceReport.Status.NEEDED,
        )
        police_report(
            self.b_emma_past, self.emma, self._at(self.b_emma_past.check_in) + d(hours=24),
            PoliceReport.Status.FILED, marked_by=self.staff2,
            marked_at=self._at(self.b_emma_past.check_in) + d(hours=18),
        )
        police_report(
            self.b_lotte_upcoming, self.lotte, self._at(self.b_lotte_upcoming.check_in) + d(hours=24),
            PoliceReport.Status.NEEDED,
        )
        police_report(
            self.b_sophie, self.sophie, self._at(self.b_sophie.check_in) + d(hours=24),
            PoliceReport.Status.NEEDED,
        )
        police_report(
            self.b_mark, self.mark, self._at(self.b_mark.check_in) + d(hours=24),
            PoliceReport.Status.NEEDED,
        )
        police_report(  # Indonesian citizens don't need an STM report
            self.b_rina, self.rina, self._at(self.b_rina.check_in) + d(hours=24),
            PoliceReport.Status.NOT_REQUIRED,
        )

    # ------------------------------------------------------------ messaging

    def _build_messaging(self):
        confirmed = MessageTemplate.objects.get_or_create(
            organization=self.canggu, name="booking_confirmed", language="en",
            defaults=dict(
                body_en="Hi {{1}}, your stay at {{2}} from {{3}} to {{4}} is confirmed. "
                        "Reply here if you need anything!",
                body_id="Hai {{1}}, menginap Anda di {{2}} dari {{3}} sampai {{4}} sudah dikonfirmasi. "
                        "Balas pesan ini jika butuh bantuan.",
                is_approved=True,
            ),
        )[0]
        staff_alert = MessageTemplate.objects.get_or_create(
            organization=self.canggu, name="staff_task_alert", language="en",
            defaults=dict(
                body_en="New request from {{1}} at {{2}}: {{3}}. Please check the dashboard.",
                is_approved=True,
            ),
        )[0]
        MessageTemplate.objects.get_or_create(
            organization=self.ubud, name="stm_reminder", language="id",
            defaults=dict(
                body_id="Pengingat: laporan STM untuk tamu {{1}} jatuh tempo dalam 24 jam.",
                is_approved=False,  # still waiting on WhatsApp approval
            ),
        )

        d = timezone.timedelta
        staff_convo = Conversation.objects.get_or_create(
            organization=self.canggu, phone=self.staff1.phone,
            defaults={"last_inbound_at": self.now - d(minutes=25)},
        )[0]
        OutboundMessage.objects.get_or_create(
            organization=self.canggu, conversation=staff_convo, template=staff_alert,
            defaults=dict(
                body="New request from James Whitfield at Villa Sunset Canggu: Airport transfer.",
                status=OutboundMessage.Status.SENT, provider_message_id="wamid.demo001",
                sent_at=self.now - d(minutes=29),
            ),
        )
        InboundMessage.objects.get_or_create(
            organization=self.canggu, conversation=staff_convo,
            defaults=dict(
                body="Got it, heading over now.", provider_message_id="wamid.demo001-reply",
                received_at=self.now - d(minutes=25),
            ),
        )

        james_convo = Conversation.objects.get_or_create(
            organization=self.canggu, phone=self.james.phone, guest=self.james,
            defaults={"last_inbound_at": self.now - d(hours=3)},
        )[0]
        InboundMessage.objects.get_or_create(
            organization=self.canggu, conversation=james_convo,
            defaults=dict(
                body="Hi, we just landed and our flight was early - could we get picked up at 2pm instead?",
                provider_message_id="wamid.demo003", received_at=self.now - d(hours=3),
            ),
        )
        OutboundMessage.objects.get_or_create(
            organization=self.canggu, conversation=james_convo,
            defaults=dict(
                body="No problem James, updating the driver now - see you at 2pm.",
                status=OutboundMessage.Status.SENT, provider_message_id="wamid.demo004",
                sent_at=self.now - d(hours=2, minutes=50),
            ),
        )

        emma_convo = Conversation.objects.get_or_create(
            organization=self.canggu, phone="+491701234567", guest=self.emma,
            defaults={"last_inbound_at": self.now - d(days=2)},
        )[0]
        OutboundMessage.objects.get_or_create(
            organization=self.canggu, conversation=emma_convo, template=confirmed,
            defaults=dict(
                body="Hi Emma, your stay at Villa Ombak Biru is confirmed.",
                status=OutboundMessage.Status.DELIVERED, provider_message_id="wamid.demo002",
                sent_at=self.now - d(days=32),
            ),
        )
        InboundMessage.objects.get_or_create(
            organization=self.canggu, conversation=emma_convo,
            defaults=dict(
                body="Thank you! One more question, is early check-in possible?",
                provider_message_id="wamid.demo005", received_at=self.now - d(days=2),
            ),
        )

        sophie_convo = Conversation.objects.get_or_create(
            organization=self.ubud, phone="+33612345678", guest=self.sophie,
        )[0]
        OutboundMessage.objects.get_or_create(
            organization=self.ubud, conversation=sophie_convo,
            defaults=dict(
                body="Pengingat: laporan STM untuk tamu Sophie Laurent jatuh tempo dalam 24 jam.",
                status=OutboundMessage.Status.FAILED,
                error="Template not yet approved by WhatsApp - message rejected.",
            ),
        )

    # ------------------------------------------------------------ marketing

    def _build_marketing(self):
        def experience(org, name_en, name_id, operator, phone, commission, villas):
            exp, _ = Experience.objects.get_or_create(
                organization=org, name_en=name_en,
                defaults=dict(
                    name_id=name_id, operator_name=operator, operator_phone=phone,
                    commission_percent=commission,
                ),
            )
            exp.villas.add(*villas)
            return exp

        experience(self.canggu, "Surf Lesson at Canggu Beach", "Kelas Selancar di Pantai Canggu",
                   "Canggu Surf School", "+62361555001", "20.00",
                   [self.villa_sunset, self.villa_ombak, self.villa_kelapa])
        experience(self.canggu, "Private Chef Seafood BBQ", "Chef Pribadi BBQ Seafood",
                   "Bali Private Chefs Co", "+62361555002", "10.00",
                   [self.villa_sunset, self.villa_ombak, self.villa_kelapa])
        experience(self.ubud, "Monkey Forest Tour", "Wisata Monkey Forest",
                   "Ubud Nature Tours", "+62361555010", "15.00",
                   [self.villa_hutan, self.villa_padi])
        experience(self.ubud, "Sunrise Trekking Mount Batur", "Trekking Sunrise Gunung Batur",
                   "Batur Adventure Guides", "+62361555011", "18.00",
                   [self.villa_hutan, self.villa_padi])
        experience(self.ubud, "Balinese Cooking Class", "Kelas Memasak Bali",
                   "Ubud Culinary Studio", "+62361555012", "12.00",
                   [self.villa_hutan, self.villa_padi, self.villa_sunset])

        d = timezone.timedelta
        stay_date = self.today + d(days=30)

        def rate(villa, channel, amount):
            RateSnapshot.objects.get_or_create(
                organization=villa.organization, villa=villa, channel=channel, stay_date=stay_date,
                defaults={"amount": amount, "currency": "IDR"},
            )

        # Sunset Canggu: Airbnb is quietly undercutting the direct rate - a parity violation.
        rate(self.villa_sunset, "direct", "3200000.00")
        rate(self.villa_sunset, "airbnb", "2950000.00")
        rate(self.villa_sunset, "booking_com", "3250000.00")

        # Ombak Biru: clean parity - direct is the cheapest, as intended.
        rate(self.villa_ombak, "direct", "1800000.00")
        rate(self.villa_ombak, "airbnb", "1850000.00")
        rate(self.villa_ombak, "booking_com", "1820000.00")

    # ------------------------------------------------------------ calendar

    def _build_holidays(self):
        """Illustrative only - Nyepi, Galungan and Kuningan follow the Saka
        and 210-day Pawukon calendars, not fixed Gregorian dates. Confirm
        exact dates against an official Balinese calendar before relying on
        these for real staff scheduling - see apps/core/calendar.py.
        """
        BaliHoliday.objects.get_or_create(
            name="Nyepi (Day of Silence) - DEMO DATE, VERIFY BEFORE USE",
            date=date(2026, 3, 19),
            defaults=dict(
                impact=BaliHoliday.Impact.SHUTDOWN,
                notes="Island-wide shutdown - no flights, no staff movement, no arrivals or departures.",
            ),
        )
        BaliHoliday.objects.get_or_create(
            name="Galungan - DEMO DATE, VERIFY BEFORE USE",
            date=date(2026, 4, 22),
            defaults=dict(impact=BaliHoliday.Impact.REDUCED, notes="Many staff observe this with family."),
        )
        BaliHoliday.objects.get_or_create(
            name="Kuningan - DEMO DATE, VERIFY BEFORE USE",
            date=date(2026, 5, 2),
            defaults=dict(impact=BaliHoliday.Impact.REDUCED, notes="Follows Galungan by ten days."),
        )

    # ------------------------------------------------------------ the real account's big portfolio

    def _build_big_organization(self):
        """A much larger portfolio, owned by the real account this project is
        built for rather than a placeholder demo email - everything else in
        this command is illustrative example data; this section exists so
        there's enough volume to actually feel what the product looks like
        at the top of its target range (close to the 15-villa Pro plan cap).
        """
        d = timezone.timedelta

        org, _created = Organization.objects.get_or_create(
            slug="bali-horizon",
            defaults=dict(
                name="Bali Horizon Villas",
                sync_tier=Organization.SyncTier.PREMIUM,
                plan=Organization.PlanTier.PRO,
                default_currency="IDR",
                whatsapp_number="+622112340099",
            ),
        )
        self.big_org = org

        # The real login - never created or modified here beyond linking it
        # to this organization. If it doesn't exist yet in this environment,
        # a plain (non-superuser) account is created as a fallback; where it
        # already exists (the normal case), get_or_create only fetches it.
        owner_user, _created = User.objects.get_or_create(
            email=REAL_OWNER_EMAIL, defaults={"full_name": "Alireza Keyvan"},
        )
        Membership.objects.get_or_create(user=owner_user, organization=org)
        manager_group, _created = Group.objects.get_or_create(name=MANAGER_GROUP)
        owner_user.groups.add(manager_group)

        # ---- villas ----
        villas = []
        for i, (name, area, ptype, bedrooms, bathrooms, max_guests) in enumerate(BIG_VILLAS):
            villa, _created = Villa.objects.get_or_create(
                organization=org, slug=slugify(name),
                defaults=dict(
                    name=name, area=area, property_type=ptype, bedrooms=bedrooms,
                ),
            )
            villas.append(villa)
            # Prices, size and amenities belong to the room type, not the
            # villa - so they go on the type the villa was given when it was
            # created. See the note at the top of apps/villas/models.py.
            nightly = 750_000 + bedrooms * 400_000
            category = villa.room_categories.first()
            if category is not None:
                category.max_guests = max(max_guests // max(bedrooms, 1), 1)
                category.nightly_rate = nightly
                category.monthly_rate = nightly * 22
                category.size_sqm = 30 + bathrooms * 5
                category.save()
                category.amenities.set(
                    self.rng.sample(list(self.amenities.values()), k=self.rng.randint(3, 5))
                )
            if not villa.photos.live().exists():
                VillaPhoto.objects.create(
                    organization=org, villa=villa,
                    image=_placeholder_photo(name, PHOTO_COLORS[i % len(PHOTO_COLORS)]),
                    is_cover=True,
                )
        self.big_villas = villas

        # ---- guests ----
        guests = []
        for i in range(24):
            first = FIRST_NAMES[i % len(FIRST_NAMES)]
            last = LAST_NAMES[(i * 7) % len(LAST_NAMES)]  # offset so pairing isn't index-aligned
            nationality = NATIONALITIES[i % len(NATIONALITIES)]
            guests.append(find_or_create_guest(
                org, full_name=f"{first} {last}",
                email=f"{first.lower()}.{last.lower()}{i}@example.com",
                phone=f"+1555{1000 + i:04d}",
                nationality=nationality,
            ))
        self.big_guests = guests

        # ---- bookings + payments, walking forward per villa so nothing overlaps ----
        channels = [Booking.Channel.AIRBNB, Booking.Channel.BOOKING_COM, Booking.Channel.DIRECT, Booking.Channel.WHATSAPP]
        currencies = [("IDR", 1), ("USD", 15800), ("AUD", 10400), ("EUR", 17200)]
        bookings = []
        for v_idx, villa in enumerate(villas):
            rooms = list(villa.rooms.order_by("id"))
            cursor = self.today - d(days=90)
            b_idx = 0
            while cursor < self.today + d(days=120):
                nights = self.rng.choice([2, 3, 4, 5, 7, 10, 14])
                check_in, check_out = cursor, cursor + d(days=nights)
                is_cancelled = self.rng.random() < 0.08
                guest = self.rng.choice(guests)
                booking, _created = Booking.objects.get_or_create(
                    organization=org, external_id=f"horizon-{v_idx}-{b_idx}",
                    defaults=dict(
                        villa=villa, room=rooms[b_idx % len(rooms)], guest=guest,
                        check_in=check_in, check_out=check_out,
                        channel=self.rng.choice(channels),
                        status=Booking.Status.CANCELLED if is_cancelled else Booking.Status.CONFIRMED,
                        source_detail=Booking.SourceDetail.FULL,
                        guest_count=self.rng.randint(2, max(min(villa.sleeps, 8), 2)),
                        last_synced_at=self.now,
                    ),
                )
                if not is_cancelled:
                    bookings.append(booking)
                    if not booking.payments.exists():
                        currency, rate = self.rng.choice(currencies)
                        nightly_idr = 750_000 + villa.bedrooms * 400_000
                        amount = round(nightly_idr * nights / rate, 2)
                        BookingPayment.objects.create(
                            organization=org, booking=booking, kind=BookingPayment.Kind.PAYOUT,
                            amount=str(amount), currency=currency,
                            received_on=check_in if check_in <= self.today else None,
                            is_outstanding=self.rng.random() < 0.15,
                        )
                cursor = check_out + d(days=self.rng.choice([1, 2, 3, 5, 8]))
                b_idx += 1
        self.big_bookings = bookings

        # Stand-in for the recalculation a Celery job should eventually do
        # when a booking closes - see the Guest model docstring.
        for guest in guests:
            guest_bookings = [b for b in bookings if b.guest_id == guest.id]
            if not guest_bookings:
                continue
            guest.total_stays = len(guest_bookings)
            guest.first_seen = min(b.check_in for b in guest_bookings)
            guest.last_seen = max(b.check_in for b in guest_bookings)
            guest.save(update_fields=["total_stays", "first_seen", "last_seen"])

        # ---- guest activity, on a sample of bookings ----
        activity_kinds = [
            GuestActivity.Kind.PORTAL_OPENED, GuestActivity.Kind.EXPERIENCE_VIEWED,
            GuestActivity.Kind.EXPERIENCE_BOOKED, GuestActivity.Kind.REQUEST_MADE,
        ]
        for booking in self.rng.sample(bookings, k=min(len(bookings), 30)):
            self._activity(
                booking.guest, self.rng.choice(activity_kinds), booking=booking,
                occurred_at=self._at(booking.check_in),
            )

        # ---- compliance: one NIB for the business, PBG + SLF per villa ----
        expiry_offsets = [-20, 15, 45, 200, 400]  # mix of expired, urgent, and healthy
        nib = self._doc_type("Business licence (NIB)")
        pbg = self._doc_type("Building approval (PBG)")
        slf = self._doc_type("Building safety certificate (SLF)")
        ComplianceDocument.objects.get_or_create(
            organization=org, villa=None, document_type=nib,
            reference_number="NIB-8120000555111",
            defaults=dict(
                file=ContentFile(b"%PDF-1.4 demo placeholder\n", name="nib-horizon.pdf"),
                expires_on=self.today + d(days=500),
            ),
        )
        for i, villa in enumerate(villas):
            for doc_type in (pbg, slf):
                offset = expiry_offsets[(i + (doc_type == slf)) % len(expiry_offsets)]
                slug = "pbg" if doc_type == pbg else "slf"
                ComplianceDocument.objects.get_or_create(
                    organization=org, villa=villa, document_type=doc_type,
                    reference_number=f"{slug.upper()}-{2020 + i}-{i:03d}",
                    defaults=dict(
                        file=ContentFile(b"%PDF-1.4 demo placeholder\n", name=f"{slug}-{villa.slug}.pdf"),
                        expires_on=self.today + d(days=offset),
                    ),
                )

        # ---- police reports - every guest here is foreign, so every stay needs one ----
        for booking in bookings:
            deadline = self._at(booking.check_in) + d(hours=24)
            roll = self.rng.random()
            if roll < 0.6:
                status, marked_by, marked_at = PoliceReport.Status.FILED, None, deadline - d(hours=4)
            elif roll < 0.85:
                status, marked_by, marked_at = PoliceReport.Status.NEEDED, None, None
            else:
                # Deliberately overdue, regardless of when the stay actually was.
                deadline, status, marked_by, marked_at = self.now - d(hours=self.rng.randint(1, 48)), PoliceReport.Status.NEEDED, None, None
            PoliceReport.objects.get_or_create(
                organization=org, booking=booking, guest=booking.guest,
                defaults=dict(deadline=deadline, status=status, marked_done_by=marked_by, marked_done_at=marked_at),
            )

        # ---- sync history ----
        account, _created = SyncAccount.objects.get_or_create(
            organization=org, provider=SyncAccount.Provider.BEDS24,
            defaults=dict(
                label="Beds24 - main account", beds24_property_id="90210",
                refresh_token="demo-refresh-token-do-not-use-in-production",
                last_success_at=self.now - d(minutes=45),
            ),
        )
        for i in range(5):
            SyncRun.objects.get_or_create(
                organization=org, account=account,
                trigger=SyncRun.Trigger.SCHEDULED if i % 2 else SyncRun.Trigger.WEBHOOK,
                result=SyncRun.Result.OK, bookings_created=self.rng.randint(0, 3),
                bookings_updated=self.rng.randint(0, 4),
                defaults=dict(message="Routine sync.", finished_at=self.now - d(hours=i * 3)),
            )
        RawPayload.objects.get_or_create(
            organization=org, account=account, endpoint="/bookings",
            defaults=dict(
                body={"bookId": "90301", "roomId": 501, "status": "confirmed"},
                processed_at=self.now - d(minutes=45),
            ),
        )

        # ---- messaging ----
        template, _created = MessageTemplate.objects.get_or_create(
            organization=org, name="booking_confirmed", language="en",
            defaults=dict(
                body_en="Hi {{1}}, your stay at {{2}} is confirmed. Reply here if you need anything!",
                is_approved=True,
            ),
        )
        for guest in guests[:4]:
            convo, _created = Conversation.objects.get_or_create(
                organization=org, phone=guest.phone, guest=guest,
                defaults={"last_inbound_at": self.now - d(hours=self.rng.randint(1, 40))},
            )
            OutboundMessage.objects.get_or_create(
                organization=org, conversation=convo, template=template,
                defaults=dict(
                    body=f"Hi {guest.full_name.split()[0]}, your stay is confirmed.",
                    status=OutboundMessage.Status.DELIVERED, sent_at=self.now - d(hours=1),
                ),
            )
            if convo.window_is_open:
                InboundMessage.objects.get_or_create(
                    organization=org, conversation=convo,
                    defaults=dict(
                        body="Thanks, see you soon!",
                        received_at=convo.last_inbound_at,
                    ),
                )

        # ---- marketing ----
        experience_names = [
            ("Sunset Surf Lesson", "Uluwatu Surf Co", "15.00"),
            ("Private Yoga Session", "Bali Wellness Collective", "20.00"),
            ("Rice Terrace Photo Tour", "Ubud Photo Guides", "12.00"),
            ("Traditional Balinese Massage", "Jimbaran Spa Group", "18.00"),
        ]
        for name, operator, commission in experience_names:
            exp, _created = Experience.objects.get_or_create(
                organization=org, name_en=name,
                defaults={"operator_name": operator, "commission_percent": commission},
            )
            exp.villas.add(*self.rng.sample(villas, k=3))

        stay_date = self.today + d(days=45)
        for villa in villas[:3]:
            base = 750_000 + villa.bedrooms * 400_000
            for channel, jitter in [("direct", 1.0), ("airbnb", 0.94), ("booking_com", 1.03)]:
                RateSnapshot.objects.get_or_create(
                    organization=org, villa=villa, channel=channel, stay_date=stay_date,
                    defaults={"amount": str(round(base * jitter, -3)), "currency": "IDR"},
                )

    # ------------------------------------------------------------ summary

    def _print_summary(self):
        counts = {
            "Organizations": Organization.objects.count(),
            "Users": User.objects.count(),
            "Villas": Villa.objects.count(),
            "Guests": Guest.objects.count(),
            "Bookings": Booking.objects.count(),
            "Booking payments": BookingPayment.objects.count(),
            "Guest activity entries": GuestActivity.objects.count(),
            "Guest requests": GuestRequest.objects.count(),
            "Compliance documents": ComplianceDocument.objects.count(),
            "Police report reminders": PoliceReport.objects.count(),
            "WhatsApp messages": OutboundMessage.objects.count(),
            "Experiences": Experience.objects.count(),
        }
        self.stdout.write(self.style.SUCCESS("\nDemo data ready."))
        for label, count in counts.items():
            self.stdout.write(f"  {label}: {count}")
        self.stdout.write(
            f"\nDemo staff/owner logins (password: {DEMO_PASSWORD}):\n"
            f"  budi.owner@canggucoastal.example   (owner, Canggu Coastal Villas)\n"
            f"  sarah.manager@canggucoastal.example (manager, Canggu Coastal Villas)\n"
            f"  made.staff@canggucoastal.example    (staff, scoped to Villa Sunset Canggu)\n"
            f"  john.owner@ubudgreen.example        (owner, Ubud Green Retreats - basic tier)\n"
        )
        self.stdout.write(
            f"\n{REAL_OWNER_EMAIL} is now Owner of Bali Horizon Villas "
            f"({len(self.big_villas)} villas, {len(self.big_bookings)} bookings, "
            f"{len(self.big_guests)} guests) - its own password is untouched."
        )

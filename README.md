# Bali Villa Management Dashboard

A lightweight property management dashboard for Bali villa operators running
3-15 villas. Booking sync, WhatsApp-native workflow, and honest compliance
tracking.

Product decisions, rules and build order live in [CLAUDE.md](CLAUDE.md); the
feature list is in [villa-dashboard-features.md](villa-dashboard-features.md).
Read both before adding anything - several features are excluded on purpose.

## Running it locally

```bash
source venv/bin/activate
pip install -r requirements/dev.txt

cp .env.example .env          # then set SECRET_KEY
docker compose up -d          # Postgres on 5433, Redis on 6380
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Ports are deliberately 5433/6380 so the containers do not collide with a
Postgres or Redis already installed on the machine.

Tailwind is a separate process during development:

```bash
npm install
npm run css                   # watch mode
```

## Commands

| Task | Command |
| --- | --- |
| Tests | `pytest` |
| One test file | `pytest apps/guests/tests/test_activity.py` |
| One test | `pytest apps/guests/tests/test_activity.py::test_returning_guest_is_matched_not_duplicated` |
| Lint | `ruff check .` |
| Autofix | `ruff check . --fix` |
| Migrations | `python manage.py makemigrations && python manage.py migrate` |
| Translations | `python manage.py makemessages -l id && python manage.py compilemessages` |
| Background worker | `celery -A config worker -l info` |
| Scheduler | `celery -A config beat -l info` |

In development, Celery tasks run inline (`CELERY_TASK_ALWAYS_EAGER`), so a
worker is only needed when testing queue behaviour itself.

## How it fits together

```
config/          settings (base/dev/prod), root urls, Ninja API root, Celery
apps/
  core/          base models, tenant scoping, money, Bali holiday calendar
  accounts/      User (email login) - staff and owners only, never guests
  organizations/ Organization (the tenant), Membership, sync tier
  villas/        Villa, photos (WebP), amenities
  guests/        Guest, activity log, requests, feedback, signed portal links
  bookings/      Booking, payments, calendar
  sync/          Beds24 (premium) + iCal (basic) ingestion
  compliance/    licence vault, STM reminders, action-needed view
  reporting/     owner dashboard, daily staff view, FX for display
  messaging/     WhatsApp Cloud API, 24-hour window, templates
  marketing/     public villa pages, direct booking, rate parity
templates/       dashboard/ guest/ public/ partials/
locale/          en, id
```

Three audiences are kept deliberately separate in the URL layout:
`/` staff and owners (session auth), `/stay/` guests (signed link, no account),
`/villa/` public villa pages (no auth), `/api/` webhooks only.

### Two ideas worth knowing before editing models

**Tenancy.** One shared database. Every client-owned row inherits
`TenantOwnedModel`, which carries an `organization` foreign key.
`OrganizationMiddleware` resolves `request.organization`; querysets get
`.for_organization(org)` and `.for_request(request)`. Views must filter
explicitly - the middleware supplies the scope, it does not enforce it.

**Sync tier honesty.** `Organization.sync_tier` is either `premium` (Beds24:
near-real-time, guest names, pricing) or `basic` (iCal: dates only, hours
behind). `Booking.source_detail` records which produced each row. Any screen
implying freshness or showing guest details must gate on
`organization.has_live_sync` or `booking.has_guest_details`. See
`templates/partials/_sync_badge.html`.

## Guest data

Guests never hold an account - they arrive through a signed, expiring link.
Their history still persists: `Guest` is deduplicated on email or phone within
an operator, and `GuestActivity` is an append-only trail of what they did, so
questions like "which nationalities book which tours" are a plain query.

Write to that trail through `apps.guests.services.log_activity`, not by
creating rows directly.

These records are personal data under Indonesia's UU PDP and, for EU guests,
GDPR. `Guest.retain_until` exists so records can be aged out - wire it to a
scheduled job before launch.

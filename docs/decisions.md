# Structural decisions

Recorded because they are expensive to reverse and are not obvious from the code.

## Multi-tenancy: shared database, row-level scoping
One deployment, one database, an `organization` foreign key on every
client-owned row. Rejected one-deployment-per-client (hosting and upgrade cost
multiplies by client count, unworkable for a two-person team at 10+ clients) and
schema-per-tenant (complicates migrations, Celery routing and local dev for
isolation we do not yet need). The trade-off accepted: a missed scope filter
leaks across clients, so scoping helpers live on the base manager and views must
filter explicitly.

## Guests have no accounts, but do have history
Signed, expiring links over WhatsApp instead of signup. A five-day stay does not
justify a password, and account recovery would be pure support burden. The
persistent record lives on `Guest` regardless - access method and data retention
are independent concerns. Nationality is already collected for the STM police
report, which is what makes nationality-segmented analysis free.

## Money stored in its original currency
`amount` plus an ISO `currency` code, exactly as the source reported it.
Converting on ingest would bake in one day's rate permanently and destroy the
true figure; OTA payouts to Bali villas are frequently not in IDR. Conversion
happens at display time in `apps/reporting/fx.py`, which returns `None` rather
than guessing when no rate is on file.

## Django 5.2 LTS
Supported to April 2028. Chosen over 6.1 for a project that will run unattended
between bursts of development, and for third-party package compatibility.

## Postgres, not SQLite
`GuestActivity.detail` and `RawPayload.body` are JSONB and get queried; Celery
adds real concurrency. Dev containers bind 5433/6380 to avoid colliding with a
Postgres or Redis already on the machine.

## Django admin as the internal ops panel
Per CLAUDE.md, no custom internal-only screens where the admin already works.
Admin classes exist for every model; `GuestActivityInline` is read-only because
the trail is append-only.

## Still open
- **Hosting region.** Singapore is the latency choice for Bali. Indonesia's UU
  PDP does not strictly require local storage for private entities, but confirm
  before committing.
- **Object storage provider.** `django-storages` with an S3-compatible backend
  is wired but unconfigured. Cloudflare R2 has no egress fees, which suits
  image-heavy public villa pages.
- **n8n.** Celery covers the scheduled work today. Revisit only if a workflow
  genuinely needs to be non-technically editable, and weigh the hosting cost.
